import os
from contextlib import contextmanager
from typing import Any

import config
from grab_module import BatchCrawler
from search_module import search_standards_with_output
from utils import ensure_dir, write_excel


@contextmanager
def working_directory(path: str):
    original_cwd = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(original_cwd)


class PipelineRunner:
    def __init__(self, task_store):
        self.task_store = task_store

    def _artifact_root(self, task_id: str) -> str:
        return os.path.join(config.get_base_dir(), "artifacts", "tasks", task_id)

    def _build_overrides(self, payload: dict[str, Any], artifact_root: str) -> dict[str, Any]:
        runtime_root = os.path.join(config.get_base_dir(), ".tmp", "worker_runtime", os.path.basename(artifact_root))
        return {
            "pdf_dir": payload.get("pdf_dir") or os.path.join(artifact_root, "pdf"),
            "temp_dir": os.path.join(runtime_root, "temp"),
            "debug_dir": os.path.join(artifact_root, "debug"),
            "headless_browser": bool(payload.get("headless", False)),
        }

    def _check_cancelled(self, task_id: str):
        if self.task_store.is_cancel_requested(task_id):
            raise RuntimeError("Task cancelled")

    def _normalize_direct_items(self, items: list[dict[str, Any]]):
        normalized = []
        for index, item in enumerate(items, 1):
            detail_url = str(item.get("detail_url", "")).strip()
            code = str(item.get("code", "")).strip()
            name = str(item.get("name", "")).strip()
            if not detail_url or not code or not name:
                raise ValueError(
                    f"direct_grab item #{index} must include detail_url, code, and name"
                )
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

    def _finalize_task_items(self, task_id, items, saved_results, failed_items):
        unique_failures = {}
        for item in failed_items:
            unique_failures[item["detail_url"]] = item

        success_count = 0
        failure_count = 0
        errors = []

        for item in items:
            detail_url = item["detail_url"]
            saved = saved_results.get(detail_url) or {}
            meta = saved.get("meta") or item
            pdf_path = saved.get("pdf_path")
            failure = unique_failures.get(detail_url)

            if failure:
                failure_count += 1
                errors.append(
                    {
                        "detail_url": detail_url,
                        "code": item.get("code"),
                        "error_type": failure.get("error_type"),
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
                )
            elif detail_url in saved_results:
                success_count += 1
                self.task_store.update_task_item(
                    task_id,
                    detail_url,
                    item_status="succeeded",
                    pdf_path=pdf_path,
                    meta_payload=meta,
                )
            else:
                failure_count += 1
                message = "No database write record captured for this item"
                errors.append(
                    {
                        "detail_url": detail_url,
                        "code": item.get("code"),
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
                )

        return success_count, failure_count, errors

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

        self._check_cancelled(task_id)
        if task_type == "keyword_search":
            search_result = search_standards_with_output(
                keywords,
                output_filename=search_output,
                log_file=task_log,
                cancel_checker=lambda: self.task_store.is_cancel_requested(task_id),
                per_keyword_limit=per_keyword_limit,
            )
            items = search_result["records"]
        elif task_type == "direct_grab":
            items = self._normalize_direct_items(payload["items"])
            write_excel(items, search_output)
        else:
            raise ValueError(f"Unsupported task type: {task_type}")

        self.task_store.upsert_task_items(task_id, items, item_status="pending")

        search_summary = self._normalize_search_summary(search_result, items)

        if not items:
            return {
                "task_id": task_id,
                "status": "succeeded",
                "summary": {"total": 0, "succeeded": 0, "failed": 0, "skipped": 0},
                "search_summary": search_summary,
                "artifacts": {
                    "search_results": search_output if os.path.exists(search_output) else None,
                    "failed_results": None,
                    "log_file": task_log,
                    "pdf_dir": overrides["pdf_dir"],
                    "debug_dir": overrides["debug_dir"],
                },
                "db_write_summary": {"table_name": payload["table_name"]},
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
            }

        crawler = BatchCrawler(
            log_file=task_log,
            cancel_checker=lambda: self.task_store.is_cancel_requested(task_id),
        )
        original_save_db = crawler.save_db
        saved_results: dict[str, dict[str, Any]] = {}

        def tracked_save_db(meta, path, table_name=payload["table_name"]):
            saved = original_save_db(meta, path, table_name)
            if saved:
                saved_results[meta.get("detail_url")] = {
                    "meta": dict(meta),
                    "pdf_path": path,
                }
            return saved

        crawler.save_db = tracked_save_db

        failed_artifact_name = None
        crawl_result = None
        try:
            with working_directory(artifact_root):
                crawl_result = crawler.run(
                    search_output,
                    generate_failed_output=True,
                    failed_keywords=keywords or None,
                )
                failed_output_path = (crawl_result or {}).get("failed_output_file")
                if failed_output_path:
                    failed_artifact_name = os.path.basename(failed_output_path)
        except RuntimeError:
            if crawler.failed_items:
                with working_directory(artifact_root):
                    failed_artifact_name = crawler.generate_failed_excel(keywords=keywords or None)
            self._finalize_task_items(task_id, items, saved_results, crawler.failed_items)
            raise

        success_count, failure_count, errors = self._finalize_task_items(
            task_id,
            items,
            saved_results,
            crawler.failed_items,
        )
        download_summary = (crawl_result or {}).get("download_summary") or self._summarize_downloads(
            items,
            crawler.download_summaries,
        )

        resolved_failed_output = None
        if failed_artifact_name:
            resolved_failed_output = os.path.join(artifact_root, failed_artifact_name)
        task_status = self._task_status_from_counts(success_count, failure_count)

        return {
            "task_id": task_id,
            "status": task_status,
            "summary": {
                "total": len(items),
                "succeeded": success_count,
                "failed": failure_count,
                "skipped": 0,
            },
            "search_summary": search_summary,
            "artifacts": {
                "search_results": search_output if os.path.exists(search_output) else None,
                "failed_results": resolved_failed_output if resolved_failed_output and os.path.exists(resolved_failed_output) else None,
                "log_file": task_log,
                "pdf_dir": overrides["pdf_dir"],
                "debug_dir": overrides["debug_dir"],
            },
            "db_write_summary": {
                "table_name": payload["table_name"],
                "task_items": len(items),
                "saved_items": len(saved_results),
            },
            "download_summary": download_summary,
            "errors": errors,
            "postprocess_status": "not_started",
        }
