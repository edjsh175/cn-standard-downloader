import json
import queue
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config

from app.db_utils import validate_table_name
from app.pipeline import PipelineRunner
from app.task_store import TaskStore
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
        if task_type not in {"keyword_search", "direct_grab"}:
            raise ValueError("task_type must be keyword_search or direct_grab")

        table_name = validate_table_name(payload.get("table_name"))
        payload["table_name"] = table_name
        payload["duplicate_policy"] = self._normalize_duplicate_policy(payload.get("duplicate_policy"))

        if task_type == "keyword_search":
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
        return self.task_store.get_task(task_id)

    def get_task(self, task_id: str):
        return self.task_store.get_task(task_id)

    def get_task_result(self, task_id: str):
        task = self.task_store.get_task(task_id)
        if not task:
            return None
        return {
            "task_id": task["id"],
            "status": task["status"],
            "result": task["result_payload"],
            "items": self.task_store.list_task_items(task_id),
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

    def do_GET(self):
        if self.path == "/health":
            self._write_json(HTTPStatus.OK, {"status": "ok"})
            return

        parts = [part for part in self.path.split("/") if part]
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

        self._write_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self):
        if self.path == "/tasks":
            try:
                payload = self._read_json()
                task = self.service.submit_task(payload)  # type: ignore[union-attr]
                self._write_json(HTTPStatus.CREATED, task)
            except ValueError as exc:
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception as exc:
                self._write_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
            return

        parts = [part for part in self.path.split("/") if part]
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
