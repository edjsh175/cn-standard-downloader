import os
from typing import Any, Callable

import config
from grab_module import BatchCrawler
from search_module import search_standards_with_output
from utils import ensure_dir, normalize_detail_url, write_excel
from app.executor_protocol import CrawlerFactory, ExcelWriter, SearchExecutor
from app.run_evidence import RunEvidence


class PipelineRunner:
    def __init__(
        self,
        task_store,
        search_executor: SearchExecutor | None = None,
        crawler_factory: CrawlerFactory | None = None,
        excel_writer: ExcelWriter | None = None,
        heartbeat_callback: Callable[[str], None] | None = None,
    ):
        self.task_store = task_store
        self.search_executor = search_executor or search_standards_with_output
        self.crawler_factory = crawler_factory or BatchCrawler
        self.excel_writer = excel_writer or write_excel
        self.heartbeat_callback = heartbeat_callback

    def _heartbeat(self, task_id: str):
        if self.heartbeat_callback is not None:
            self.heartbeat_callback(task_id)

    def _artifact_root(self, task_id: str) -> str:
        return os.path.join(config.get_base_dir(), "artifacts", "tasks", task_id)

    def _build_overrides(self, payload: dict[str, Any], artifact_root: str) -> dict[str, Any]:
        runtime_root = os.path.join(config.get_base_dir(), ".tmp", "worker_runtime", os.path.basename(artifact_root))
        headless_value = payload.get("headless")
        return {
            "pdf_dir": payload.get("pdf_dir") or os.path.join(artifact_root, "pdf"),
            "temp_dir": os.path.join(runtime_root, "temp"),
            "debug_dir": os.path.join(artifact_root, "debug"),
            "headless_browser": config.HEADLESS_BROWSER if headless_value is None else bool(headless_value),
        }

    def _check_cancelled(self, task_id: str):
        if self.task_store.is_cancel_requested(task_id):
            raise RuntimeError("Task cancelled")

    def _normalize_direct_items(self, items: list[dict[str, Any]]):
        normalized = []
        for index, item in enumerate(items, 1):
            detail_url = normalize_detail_url(item.get("detail_url"))
            code = str(item.get("code", "")).strip()
            name = str(item.get("name", "")).strip()
            if not detail_url:
                raise ValueError(f"direct_grab item #{index} must include a valid detail_url")
            normalized.append(
                {
                    "detail_url": detail_url,
                    "code": code,
                    "name": name,
                    "keyword": str(item.get("keyword", "direct")).strip() or "direct",
                    "status": "现行",
                }
            )
        return normalized

    def _build_direct_url_items(self, detail_urls: list[str]):
        normalized = []
        for index, raw_url in enumerate(detail_urls, 1):
            detail_url = normalize_detail_url(raw_url)
            if not detail_url:
                raise ValueError(f"direct_grab detail_urls item #{index} is not a supported detail url")
            normalized.append(
                {
                    "detail_url": detail_url,
                    "code": "",
                    "name": "",
                    "keyword": "direct_url",
                    "status": "现行",
                }
            )
        return normalized

    @staticmethod
    def _resolved_item_fields(item: dict[str, Any], meta: dict[str, Any] | None):
        source = meta if isinstance(meta, dict) else {}

        def resolved(key: str):
            value = source.get(key) or item.get(key)
            text = str(value or "").strip()
            return text or None

        return {
            "code": resolved("code"),
            "name": resolved("name"),
            "keyword": resolved("keyword"),
        }

    def _finalize_task_items(self, task_id, items, saved_results, processed_results, failed_items):
        unique_failures = {}
        for item in failed_items:
            unique_failures[item["detail_url"]] = item

        success_count = 0
        failure_count = 0
        write_counts = {"inserted": 0, "updated": 0, "skipped": 0, "failed": 0}
        errors = []

        for item in items:
            detail_url = item["detail_url"]
            saved = saved_results.get(detail_url) or processed_results.get(detail_url) or {}
            meta = saved.get("meta") or item
            pdf_path = saved.get("pdf_path")
            write_result = saved.get("write_result") or {}
            failure = unique_failures.get(detail_url)
            download_summary = (meta.get("download_summary") or {}) if isinstance(meta, dict) else {}
            pdf_saved = bool(pdf_path) and bool(download_summary.get("pdf_saved"))
            resolved_fields = self._resolved_item_fields(item, meta)

            if failure:
                failure_count += 1
                write_counts["failed"] += 1
                errors.append(
                    {
                        "detail_url": detail_url,
                        "code": resolved_fields["code"],
                        "error_type": failure.get("error_type"),
                        "error_code": failure.get("error_code"),
                        "message": failure.get("fail_reason"),
                    }
                )
                self.task_store.update_task_item(
                    task_id,
                    detail_url,
                    item_status="failed",
                    pdf_path=pdf_path,
                    error_message=failure.get("fail_reason"),
                    meta_payload=meta,
                    **resolved_fields,
                )
            elif detail_url in saved_results and pdf_saved:
                success_count += 1
                item_status = str(write_result.get("status") or "succeeded")
                if item_status in write_counts:
                    write_counts[item_status] += 1
                self.task_store.update_task_item(
                    task_id,
                    detail_url,
                    item_status=item_status,
                    pdf_path=pdf_path,
                    meta_payload=meta,
                    **resolved_fields,
                )
            else:
                failure_count += 1
                write_counts["failed"] += 1
                message = "No successful PDF download or database write record captured for this item"
                errors.append(
                    {
                        "detail_url": detail_url,
                        "code": resolved_fields["code"],
                        "error_type": "unknown",
                        "message": message,
                    }
                )
                self.task_store.update_task_item(
                    task_id,
                    detail_url,
                    item_status="failed",
                    error_message=message,
                    meta_payload=meta,
                    **resolved_fields,
                )

        return success_count, failure_count, write_counts, errors

    def _summarize_downloads(self, items, download_summaries):
        relevant = []
        for item in items:
            summary = download_summaries.get(item["detail_url"])
            if summary:
                relevant.append(summary)

        return {
            "total_items": len(items),
            "tracked_items": len(relevant),
            "direct_download_used": sum(1 for item in relevant if item.get("direct_download_used")),
            "download_url_resolved": sum(1 for item in relevant if item.get("download_url_resolved")),
            "session_extracted": sum(1 for item in relevant if item.get("session_extracted")),
            "pdf_saved": sum(1 for item in relevant if item.get("pdf_saved")),
        }

    @staticmethod
    def _normalize_search_summary(search_result: dict[str, Any] | None, items: list[dict[str, Any]]):
        if search_result:
            return {
                "keywords": search_result.get("keywords") or [],
                "per_keyword_limit": search_result.get("per_keyword_limit"),
                "raw_count": int(search_result.get("raw_count") or 0),
                "deduplicated_count": int(search_result.get("deduplicated_count") or len(items)),
                "per_keyword_counts": search_result.get("per_keyword_counts") or {},
            }

        return {
            "keywords": [],
            "per_keyword_limit": None,
            "raw_count": len(items),
            "deduplicated_count": len(items),
            "per_keyword_counts": {},
        }

    @staticmethod
    def _task_status_from_counts(success_count: int, failure_count: int) -> str:
        if failure_count == 0:
            return "succeeded"
        if success_count == 0:
            return "failed"
        return "partial_failed"

    def execute(self, task_id: str):
        task = self.task_store.get_task(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        payload = task["request_payload"]
        artifact_root = self._artifact_root(task_id)
        ensure_dir(artifact_root)

        overrides = self._build_overrides(payload, artifact_root)
        for path_value in (overrides["pdf_dir"], overrides["temp_dir"], overrides["debug_dir"]):
            ensure_dir(path_value)
        config.update_config(overrides)

        task_log = os.path.join(artifact_root, "task.log")
        search_output = os.path.join(artifact_root, "search_results.xlsx")
        task_type = task["task_type"]
        keywords = payload.get("keywords") or []
        per_keyword_limit = payload.get("per_keyword_limit")
        search_result = None
        evidence = RunEvidence()

        self._check_cancelled(task_id)
        self._heartbeat(task_id)
        if task_type in {"keyword_search", "search_only"}:
            phase_started = evidence.begin()
            try:
                search_result = self.search_executor(
                    keywords,
                    output_filename=search_output,
                    log_file=task_log,
                    cancel_checker=lambda: self.task_store.is_cancel_requested(task_id),
                    per_keyword_limit=per_keyword_limit,
                )
            finally:
                evidence.finish("search", phase_started, items=len((search_result or {}).get("records") or []))
            items = search_result["records"]
        elif task_type == "direct_grab":
            phase_started = evidence.begin()
            if payload.get("items"):
                items = self._normalize_direct_items(payload["items"])
            else:
                items = self._build_direct_url_items(payload.get("detail_urls") or [])
            self.excel_writer(items, search_output)
            evidence.finish("prepare_items", phase_started, items=len(items))
        else:
            raise ValueError(f"Unsupported task type: {task_type}")

        initial_item_status = "preview" if task_type == "search_only" else "pending"
        self.task_store.upsert_task_items(task_id, items, item_status=initial_item_status)

        search_summary = self._normalize_search_summary(search_result, items)

        if task_type == "search_only":
            return evidence.attach({
                "task_id": task_id,
                "status": "succeeded",
                "summary": {
                    "total": len(items),
                    "succeeded": len(items),
                    "failed": 0,
                    "skipped": 0,
                },
                "inserted": 0,
                "updated": 0,
                "skipped": 0,
                "search_summary": search_summary,
                "artifacts": {
                    "search_results": search_output if os.path.exists(search_output) else None,
                    "failed_results": None,
                    "log_file": task_log,
                    "pdf_dir": overrides["pdf_dir"],
                    "debug_dir": overrides["debug_dir"],
                },
                "db_write_summary": {
                    "table_name": payload.get("table_name") or "",
                    "duplicate_policy": payload.get("duplicate_policy", "overwrite"),
                    "task_items": len(items),
                    "saved_items": 0,
                    "inserted": 0,
                    "updated": 0,
                    "skipped": 0,
                    "failed": 0,
                },
                "download_summary": {
                    "total_items": 0,
                    "tracked_items": 0,
                    "direct_download_used": 0,
                    "download_url_resolved": 0,
                    "session_extracted": 0,
                    "pdf_saved": 0,
                },
                "errors": [],
                "postprocess_status": "not_started",
            })

        if not items:
            return evidence.attach({
                "task_id": task_id,
                "status": "succeeded",
                "summary": {"total": 0, "succeeded": 0, "failed": 0, "skipped": 0},
                "inserted": 0,
                "updated": 0,
                "skipped": 0,
                "search_summary": search_summary,
                "artifacts": {
                    "search_results": search_output if os.path.exists(search_output) else None,
                    "failed_results": None,
                    "log_file": task_log,
                    "pdf_dir": overrides["pdf_dir"],
                    "debug_dir": overrides["debug_dir"],
                },
                "db_write_summary": {
                    "table_name": payload.get("table_name") or "",
                    "duplicate_policy": payload.get("duplicate_policy", "overwrite"),
                    "task_items": 0,
                    "saved_items": 0,
                    "inserted": 0,
                    "updated": 0,
                    "skipped": 0,
                    "failed": 0,
                },
                "download_summary": {
                    "total_items": 0,
                    "tracked_items": 0,
                    "direct_download_used": 0,
                    "download_url_resolved": 0,
                    "session_extracted": 0,
                    "pdf_saved": 0,
                },
                "errors": [],
                "postprocess_status": "not_started",
            })

        crawler = self.crawler_factory(
            log_file=task_log,
            cancel_checker=lambda: self.task_store.is_cancel_requested(task_id),
            duplicate_policy=payload.get("duplicate_policy", "overwrite"),
        )
        original_save_db = crawler.save_db
        saved_results: dict[str, dict[str, Any]] = {}

        def tracked_save_db(meta, path, table_name=payload["table_name"]):
            saved = original_save_db(meta, path, table_name)
            if saved and saved.get("status") in {"inserted", "updated", "skipped"}:
                meta["write_result"] = dict(saved)
                saved_results[meta.get("detail_url")] = {
                    "meta": dict(meta),
                    "pdf_path": path,
                    "write_result": dict(saved),
                }
            return saved

        crawler.save_db = tracked_save_db

        failed_artifact_name = None
        crawl_result = None
        try:
            self._heartbeat(task_id)
            phase_started = evidence.begin()
            crawl_result = crawler.run(
                search_output,
                generate_failed_output=True,
                failed_keywords=keywords or None,
                failed_output_dir=artifact_root,
            )
            failed_output_path = (crawl_result or {}).get("failed_output_file")
            if failed_output_path:
                failed_artifact_name = os.path.basename(failed_output_path)
            evidence.finish("download", phase_started, items=len(items))
        except RuntimeError:
            if crawler.failed_items:
                failed_output_path = crawler.generate_failed_excel(
                    keywords=keywords or None,
                    output_dir=artifact_root,
                )
                if failed_output_path:
                    failed_artifact_name = os.path.basename(failed_output_path)
            self._finalize_task_items(task_id, items, saved_results, crawler.processed_results, crawler.failed_items)
            raise

        self._heartbeat(task_id)
        phase_started = evidence.begin()
        success_count, failure_count, write_counts, errors = self._finalize_task_items(
            task_id,
            items,
            saved_results,
            crawler.processed_results,
            crawler.failed_items,
        )
        evidence.finish("finalize", phase_started, succeeded=success_count, failed=failure_count)
        download_summary = (crawl_result or {}).get("download_summary") or self._summarize_downloads(
            items,
            crawler.download_summaries,
        )

        resolved_failed_output = None
        if failed_artifact_name:
            resolved_failed_output = os.path.join(artifact_root, failed_artifact_name)
        task_status = self._task_status_from_counts(success_count, failure_count)

        return evidence.attach({
            "task_id": task_id,
            "status": task_status,
            "summary": {
                "total": len(items),
                "succeeded": success_count,
                "failed": failure_count,
                "skipped": write_counts["skipped"],
            },
            "inserted": write_counts["inserted"],
            "updated": write_counts["updated"],
            "skipped": write_counts["skipped"],
            "search_summary": search_summary,
            "artifacts": {
                "search_results": search_output if os.path.exists(search_output) else None,
                "failed_results": resolved_failed_output if resolved_failed_output and os.path.exists(resolved_failed_output) else None,
                "log_file": task_log,
                "pdf_dir": overrides["pdf_dir"],
                "debug_dir": overrides["debug_dir"],
            },
            "db_write_summary": {
                "table_name": payload.get("table_name") or "",
                "duplicate_policy": payload.get("duplicate_policy", "overwrite"),
                "task_items": len(items),
                "saved_items": write_counts["inserted"] + write_counts["updated"],
                "inserted": write_counts["inserted"],
                "updated": write_counts["updated"],
                "skipped": write_counts["skipped"],
                "failed": write_counts["failed"],
            },
            "download_summary": download_summary,
            "errors": errors,
            "postprocess_status": "not_started",
        })
