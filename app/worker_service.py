import json
import hmac
import mimetypes
import os
import queue
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, urlparse

import config

from app.agent_contract import annotate_errors, build_agent_status, get_capabilities
from app.db_utils import validate_table_name
from app.pipeline import PipelineRunner
from app.task_store import DEFAULT_BUSINESS_TABLE_NAME, TaskStore
from utils import extract_detail_urls_from_text, normalize_detail_url


class TaskWorkerService:
    def __init__(self):
        self.task_store = TaskStore()
        self.pipeline = PipelineRunner(self.task_store)
        self.task_queue = queue.Queue()

    @staticmethod
    def _normalize_per_keyword_limit(value):
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        if isinstance(value, bool):
            raise ValueError("per_keyword_limit must be a positive integer")

        try:
            normalized = int(value)
        except (TypeError, ValueError):
            raise ValueError("per_keyword_limit must be a positive integer") from None

        if normalized <= 0:
            raise ValueError("per_keyword_limit must be a positive integer")
        return normalized

    @staticmethod
    def _normalize_detail_urls(detail_urls):
        if detail_urls is None:
            return []
        if not isinstance(detail_urls, list):
            raise ValueError("detail_urls must be a list of strings")

        normalized = []
        seen = set()
        for index, raw_url in enumerate(detail_urls, 1):
            canonical = normalize_detail_url(raw_url)
            if not canonical:
                raise ValueError(f"detail_urls item #{index} is not a supported detail url")
            if canonical in seen:
                continue
            seen.add(canonical)
            normalized.append(canonical)
        return normalized

    @staticmethod
    def _normalize_duplicate_policy(value):
        if value is None:
            return "overwrite"
        normalized = str(value).strip().lower()
        if normalized not in {"overwrite", "skip"}:
            raise ValueError("duplicate_policy must be overwrite or skip")
        return normalized

    def submit_task(self, payload: dict):
        task_type = payload.get("task_type")
        if task_type not in {"keyword_search", "direct_grab", "search_only"}:
            raise ValueError("task_type must be keyword_search, direct_grab, or search_only")

        if task_type in {"keyword_search", "direct_grab"}:
            raw_table_name = str(payload.get("table_name") or "").strip()
            table_name = validate_table_name(raw_table_name or DEFAULT_BUSINESS_TABLE_NAME)
            payload["table_name"] = table_name
            payload["duplicate_policy"] = self._normalize_duplicate_policy(payload.get("duplicate_policy"))
        else:
            raw_table_name = str(payload.get("table_name") or "").strip()
            payload["table_name"] = validate_table_name(raw_table_name) if raw_table_name else ""

        if task_type in {"keyword_search", "search_only"}:
            keywords = payload.get("keywords")
            if not isinstance(keywords, list) or not [kw for kw in keywords if str(kw).strip()]:
                raise ValueError("keywords must be a non-empty list")
            payload["keywords"] = [str(keyword).strip() for keyword in keywords if str(keyword).strip()]
            payload["per_keyword_limit"] = self._normalize_per_keyword_limit(payload.get("per_keyword_limit"))

        if task_type == "direct_grab":
            items = payload.get("items")
            if items is not None:
                if not isinstance(items, list) or not items:
                    raise ValueError("items must be a non-empty list")
            else:
                detail_urls = self._normalize_detail_urls(payload.get("detail_urls"))
                url_text = payload.get("url_text")
                if url_text is not None and not isinstance(url_text, str):
                    raise ValueError("url_text must be a string")

                extracted_urls = extract_detail_urls_from_text(url_text or "")
                merged_urls = []
                seen = set()
                for detail_url in detail_urls + extracted_urls:
                    if detail_url in seen:
                        continue
                    seen.add(detail_url)
                    merged_urls.append(detail_url)

                if not merged_urls:
                    raise ValueError("direct_grab requires non-empty items, detail_urls, or url_text")
                payload["detail_urls"] = merged_urls

        task_id = self.task_store.create_task(task_type, payload)
        self.task_queue.put(task_id)
        return self.get_task(task_id)

    def list_tables(self):
        return self.task_store.list_tables()

    def get_capabilities(self):
        return get_capabilities()

    @staticmethod
    def _task_artifact_root(task_id: str) -> str:
        return os.path.join(config.get_base_dir(), "artifacts", "tasks", task_id)

    @staticmethod
    def _artifact_url(task_id: str, artifact_name: str) -> str:
        return f"api/tasks/{task_id}/artifacts/{artifact_name}"

    @staticmethod
    def _pdf_url(task_id: str, item_id: int) -> str:
        return f"api/tasks/{task_id}/items/{item_id}/pdf"

    def _artifact_path(self, task_id: str, artifact_name: str) -> str | None:
        task = self.task_store.get_task(task_id)
        if not task:
            return None

        artifact_root = self._task_artifact_root(task_id)
        if artifact_name == "search_results":
            path = os.path.join(artifact_root, "search_results.xlsx")
            return path if os.path.exists(path) else None
        if artifact_name == "log_file":
            path = os.path.join(artifact_root, "task.log")
            return path if os.path.exists(path) else None
        if artifact_name == "failed_results":
            result_payload = task.get("result_payload") or {}
            artifacts = result_payload.get("artifacts") or {}
            path = artifacts.get("failed_results")
            if not path:
                return None
            resolved = os.path.abspath(path)
            if not os.path.exists(resolved):
                return None
            return resolved
        return None

    def get_artifact_file(self, task_id: str, artifact_name: str):
        path = self._artifact_path(task_id, artifact_name)
        if not path:
            return None
        return {"path": path, "download_name": os.path.basename(path)}

    def get_task_item_pdf(self, task_id: str, item_id: int):
        item = self.task_store.get_task_item(task_id, item_id)
        if not item:
            return None
        pdf_path = item.get("pdf_path")
        if not pdf_path:
            return None
        resolved = os.path.abspath(str(pdf_path))
        task_root = os.path.abspath(self._task_artifact_root(task_id))
        try:
            common_root = os.path.commonpath([resolved, task_root])
        except ValueError:
            return None
        if common_root != task_root or not os.path.exists(resolved):
            return None
        return {"path": resolved, "download_name": os.path.basename(resolved)}

    def _attach_result_urls(self, task_id: str, result_payload: dict | None):
        if result_payload is None:
            return None
        payload = dict(result_payload)
        artifacts = dict(payload.get("artifacts") or {})
        artifact_urls = {}
        for artifact_name in ("search_results", "failed_results", "log_file"):
            if artifacts.get(artifact_name):
                artifact_urls[artifact_name] = self._artifact_url(task_id, artifact_name)
        if artifact_urls:
            payload["artifact_urls"] = artifact_urls
        return payload

    def _attach_item_urls(self, task_id: str, items: list[dict]):
        normalized = []
        for item in items:
            row = dict(item)
            meta = row.get("meta_payload")
            if isinstance(meta, dict):
                for key in ("code", "name", "keyword"):
                    value = str(meta.get(key) or "").strip()
                    if value and not row.get(key):
                        row[key] = value
            if row.get("pdf_path"):
                row["pdf_download_url"] = self._pdf_url(task_id, int(row["id"]))
            normalized.append(row)
        return normalized

    @staticmethod
    def _attach_error_display_fields(result_payload: dict | None, items: list[dict]):
        if result_payload is None:
            return None
        payload = dict(result_payload)
        item_by_url = {item.get("detail_url"): item for item in items}
        errors = []
        for error in payload.get("errors") or []:
            row = dict(error)
            item = item_by_url.get(row.get("detail_url")) or {}
            for key in ("code", "name"):
                if not row.get(key) and item.get(key):
                    row[key] = item[key]
            errors.append(row)
        if errors:
            payload["errors"] = annotate_errors(errors)
        return payload

    @staticmethod
    def _attach_agent_status(task: dict, result_payload: dict | None = None):
        task_type = task.get("task_type")
        status = task.get("status")
        payload = result_payload if result_payload is not None else task.get("result_payload")
        return build_agent_status(task_type, status, payload, task.get("error_message"))

    def get_task(self, task_id: str):
        task = self.task_store.get_task(task_id)
        if not task:
            return None
        task = dict(task)
        task["result_payload"] = self._attach_result_urls(task_id, task.get("result_payload"))
        task["result_payload"] = self._attach_error_display_fields(task["result_payload"], [])
        task["agent_status"] = self._attach_agent_status(task)
        return task

    def get_task_result(self, task_id: str):
        task = self.task_store.get_task(task_id)
        if not task:
            return None
        items = self._attach_item_urls(task_id, self.task_store.list_task_items(task_id))
        result = self._attach_result_urls(task_id, task.get("result_payload"))
        result = self._attach_error_display_fields(result, items)
        agent_status = self._attach_agent_status(task, result)
        return {
            "task_id": task["id"],
            "status": task["status"],
            "agent_status": agent_status,
            "result": result,
            "items": items,
            "error_message": task["error_message"],
        }

    def cancel_task(self, task_id: str):
        task = self.task_store.get_task(task_id)
        if not task:
            return None
        self.task_store.request_cancel(task_id)
        return self.task_store.get_task(task_id)

    @staticmethod
    def _result_error_message(result: dict) -> str | None:
        summary = result.get("summary") or {}
        failed_count = int(summary.get("failed") or 0)
        if failed_count <= 0:
            return None
        errors = result.get("errors") or []
        if errors:
            message = str(errors[0].get("message") or "").strip()
            if message:
                return message
        return f"{failed_count} item(s) failed"

    def process_queue_forever(self):
        while True:
            task_id = self.task_queue.get()
            try:
                if self.task_store.is_cancel_requested(task_id):
                    self.task_store.mark_cancelled(task_id)
                    continue

                self.task_store.mark_running(task_id)
                result = self.pipeline.execute(task_id)
                if self.task_store.is_cancel_requested(task_id):
                    self.task_store.mark_cancelled(task_id, result_payload=result)
                elif result.get("status") == "succeeded":
                    self.task_store.mark_succeeded(task_id, result)
                else:
                    self.task_store.mark_completed(
                        task_id,
                        result.get("status", "failed"),
                        result,
                        error_message=self._result_error_message(result),
                    )
            except RuntimeError as exc:
                if str(exc) == "Task cancelled":
                    partial = self.get_task_result(task_id)
                    self.task_store.mark_cancelled(task_id, result_payload=partial)
                else:
                    self.task_store.mark_failed(task_id, str(exc))
            except Exception as exc:
                self.task_store.mark_failed(task_id, str(exc))
            finally:
                self.task_queue.task_done()


class WorkerRequestHandler(BaseHTTPRequestHandler):
    service: TaskWorkerService | None = None

    def log_message(self, format, *args):
        return

    def _read_json(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length == 0:
            return {}
        raw_body = self.rfile.read(content_length)
        return json.loads(raw_body.decode("utf-8"))

    def _write_json(self, status: int, payload: dict):
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _write_file(self, status: int, path: str, download_name: str, as_attachment: bool = True):
        with open(path, "rb") as file_obj:
            data = file_obj.read()
        content_type = mimetypes.guess_type(download_name)[0] or "application/octet-stream"
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if as_attachment:
            fallback_name = download_name.encode("ascii", "ignore").decode("ascii").replace('"', "_") or "download"
            encoded_name = quote(download_name, safe="")
            disposition = f"attachment; filename=\"{fallback_name}\"; filename*=UTF-8''{encoded_name}"
            self.send_header("Content-Disposition", disposition)
        self.end_headers()
        self.wfile.write(data)

    @staticmethod
    def _normalize_path(path: str):
        return [part for part in path.split("/") if part]

    @staticmethod
    def _requires_auth(path: str) -> bool:
        if path in {"/health", "/api/health"}:
            return False
        parts = WorkerRequestHandler._normalize_path(path)
        return bool(parts and parts[0] in {"api", "tasks"})

    def _has_valid_bearer_token(self) -> bool:
        expected_token = str(getattr(config, "WORKER_API_TOKEN", "") or "").strip()
        if not expected_token:
            return False

        authorization = str(self.headers.get("Authorization") or "").strip()
        scheme, separator, token = authorization.partition(" ")
        if separator != " " or scheme.lower() != "bearer":
            return False
        return hmac.compare_digest(token.strip(), expected_token)

    def _authorize_request(self, path: str) -> bool:
        if not self._requires_auth(path):
            return True
        if self._has_valid_bearer_token():
            return True
        self._write_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
        return False

    @staticmethod
    def _static_root():
        return os.path.join(config.get_base_dir(), "web", "dist")

    def _serve_static(self, raw_path: str):
        static_root = os.path.abspath(self._static_root())
        if not os.path.isdir(static_root):
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "web app not built"})
            return

        request_path = raw_path.lstrip("/") or "index.html"
        resolved = os.path.abspath(os.path.join(static_root, request_path))
        try:
            common_root = os.path.commonpath([resolved, static_root])
        except ValueError:
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return

        if common_root != static_root:
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return

        if os.path.isfile(resolved):
            self._write_file(HTTPStatus.OK, resolved, os.path.basename(resolved), as_attachment=False)
            return

        index_path = os.path.join(static_root, "index.html")
        if os.path.isfile(index_path):
            self._write_file(HTTPStatus.OK, index_path, "index.html", as_attachment=False)
            return

        self._write_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if not self._authorize_request(path):
            return

        if path in {"/health", "/api/health"}:
            self._write_json(HTTPStatus.OK, {"status": "ok"})
            return

        if path == "/api/capabilities":
            try:
                capabilities = self.service.get_capabilities()  # type: ignore[union-attr]
                self._write_json(HTTPStatus.OK, capabilities)
            except Exception as exc:
                self._write_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
            return

        if path == "/api/tables":
            try:
                tables = self.service.list_tables()  # type: ignore[union-attr]
                self._write_json(HTTPStatus.OK, {"tables": tables})
            except Exception as exc:
                self._write_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
            return

        parts = self._normalize_path(path)
        if parts[:1] == ["api"]:
            parts = parts[1:]

        if len(parts) == 2 and parts[0] == "tasks":
            task = self.service.get_task(parts[1])  # type: ignore[union-attr]
            if not task:
                self._write_json(HTTPStatus.NOT_FOUND, {"error": "task not found"})
                return
            self._write_json(HTTPStatus.OK, task)
            return

        if len(parts) == 3 and parts[0] == "tasks" and parts[2] == "result":
            result = self.service.get_task_result(parts[1])  # type: ignore[union-attr]
            if not result:
                self._write_json(HTTPStatus.NOT_FOUND, {"error": "task not found"})
                return
            self._write_json(HTTPStatus.OK, result)
            return

        if len(parts) == 4 and parts[0] == "tasks" and parts[2] == "artifacts":
            artifact = self.service.get_artifact_file(parts[1], parts[3])  # type: ignore[union-attr]
            if not artifact:
                self._write_json(HTTPStatus.NOT_FOUND, {"error": "artifact not found"})
                return
            self._write_file(HTTPStatus.OK, artifact["path"], artifact["download_name"])
            return

        if len(parts) == 5 and parts[0] == "tasks" and parts[2] == "items" and parts[4] == "pdf":
            try:
                item_id = int(parts[3])
            except ValueError:
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid item id"})
                return
            artifact = self.service.get_task_item_pdf(parts[1], item_id)  # type: ignore[union-attr]
            if not artifact:
                self._write_json(HTTPStatus.NOT_FOUND, {"error": "pdf not found"})
                return
            self._write_file(HTTPStatus.OK, artifact["path"], artifact["download_name"])
            return

        if path.startswith("/api/"):
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return

        self._serve_static(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if not self._authorize_request(path):
            return

        if path in {"/tasks", "/api/tasks"}:
            try:
                payload = self._read_json()
                task = self.service.submit_task(payload)  # type: ignore[union-attr]
                self._write_json(HTTPStatus.CREATED, task)
            except ValueError as exc:
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception as exc:
                self._write_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
            return

        parts = self._normalize_path(path)
        if parts[:1] == ["api"]:
            parts = parts[1:]
        if len(parts) == 3 and parts[0] == "tasks" and parts[2] == "cancel":
            task = self.service.cancel_task(parts[1])  # type: ignore[union-attr]
            if not task:
                self._write_json(HTTPStatus.NOT_FOUND, {"error": "task not found"})
                return
            self._write_json(HTTPStatus.OK, task)
            return

        self._write_json(HTTPStatus.NOT_FOUND, {"error": "not found"})


def run_worker_server(host=None, port=None):
    service = TaskWorkerService()
    WorkerRequestHandler.service = service

    server = ThreadingHTTPServer(
        (host or config.WORKER_HOST, int(port or config.WORKER_PORT)),
        WorkerRequestHandler,
    )
    print(f"Worker server listening on http://{server.server_address[0]}:{server.server_address[1]}")
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        service.process_queue_forever()
    finally:
        server.shutdown()
        server.server_close()
