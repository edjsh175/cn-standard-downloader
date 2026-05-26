import http.client
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

import config
from app.worker_service import TaskWorkerService, WorkerRequestHandler


class FakeTaskStore:
    def __init__(self):
        self.created_task_type = None
        self.created_payload = None
        self.item = None

    def create_task(self, task_type, payload):
        self.created_task_type = task_type
        self.created_payload = dict(payload)
        return "task-1"

    def get_task(self, task_id):
        return {
            "id": task_id,
            "task_type": self.created_task_type,
            "status": "pending",
            "table_name": (self.created_payload or {}).get("table_name", ""),
            "request_payload": self.created_payload,
            "result_payload": None,
            "error_message": None,
            "cancel_requested": False,
            "created_at": "2026-05-25T00:00:00",
            "started_at": None,
            "finished_at": None,
            "updated_at": "2026-05-25T00:00:00",
        }

    def get_task_item(self, task_id, item_id):
        return self.item


class FakeHttpService:
    def list_tables(self):
        return ["gb_standards"]

    def get_task(self, task_id):
        return {
            "id": task_id,
            "task_type": "search_only",
            "status": "succeeded",
            "table_name": "",
            "request_payload": {"task_type": "search_only", "keywords": ["AI"]},
            "result_payload": None,
            "error_message": None,
            "cancel_requested": False,
            "created_at": "2026-05-25T00:00:00",
            "started_at": None,
            "finished_at": None,
            "updated_at": "2026-05-25T00:00:00",
        }

    def get_task_result(self, task_id):
        return {
            "task_id": task_id,
            "status": "succeeded",
            "result": None,
            "items": [],
            "error_message": None,
        }

    def get_task_item_pdf(self, task_id, item_id):
        return None

    def submit_task(self, payload):
        return {
            "id": "task-1",
            "task_type": payload.get("task_type", "search_only"),
            "status": "pending",
            "table_name": payload.get("table_name", ""),
            "request_payload": payload,
            "result_payload": None,
            "error_message": None,
            "cancel_requested": False,
            "created_at": "2026-05-25T00:00:00",
            "started_at": None,
            "finished_at": None,
            "updated_at": "2026-05-25T00:00:00",
        }


def make_service(store=None):
    service = TaskWorkerService.__new__(TaskWorkerService)
    service.task_store = store or FakeTaskStore()
    service.task_queue = type("FakeQueue", (), {"put": lambda self, task_id: None})()
    return service


class WorkerApiAuthTests(unittest.TestCase):
    def setUp(self):
        self.previous_token = getattr(config, "WORKER_API_TOKEN", "")
        config.WORKER_API_TOKEN = "secret-token"
        WorkerRequestHandler.service = FakeHttpService()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), WorkerRequestHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.server_address

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        config.WORKER_API_TOKEN = self.previous_token

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=5)
        try:
            payload = None if body is None else json.dumps(body).encode("utf-8")
            request_headers = dict(headers or {})
            if payload is not None:
                request_headers.setdefault("Content-Type", "application/json")
            connection.request(method, path, body=payload, headers=request_headers)
            response = connection.getresponse()
            data = response.read()
            return response.status, json.loads(data.decode("utf-8")) if data else None
        finally:
            connection.close()

    def test_health_does_not_require_token(self):
        status, payload = self.request("GET", "/health")

        self.assertEqual(status, 200)
        self.assertEqual(payload, {"status": "ok"})

    def test_api_health_does_not_require_token(self):
        status, payload = self.request("GET", "/api/health")

        self.assertEqual(status, 200)
        self.assertEqual(payload, {"status": "ok"})

    def test_api_request_without_token_is_rejected(self):
        status, payload = self.request("GET", "/api/tables")

        self.assertEqual(status, 401)
        self.assertEqual(payload, {"error": "unauthorized"})

    def test_tasks_alias_without_token_is_rejected(self):
        status, payload = self.request("GET", "/tasks/task-1")

        self.assertEqual(status, 401)
        self.assertEqual(payload, {"error": "unauthorized"})

    def test_pdf_download_without_token_is_rejected(self):
        status, payload = self.request("GET", "/api/tasks/task-1/items/1/pdf")

        self.assertEqual(status, 401)
        self.assertEqual(payload, {"error": "unauthorized"})

    def test_api_request_with_bearer_token_is_allowed(self):
        status, payload = self.request(
            "POST",
            "/api/tasks",
            {"task_type": "search_only", "keywords": ["AI"]},
            {"Authorization": "Bearer secret-token"},
        )

        self.assertEqual(status, 201)
        self.assertEqual(payload["id"], "task-1")


class TaskWorkerServiceValidationTests(unittest.TestCase):
    def test_search_only_rejects_invalid_per_keyword_limit(self):
        service = make_service()

        with self.assertRaisesRegex(ValueError, "per_keyword_limit must be a positive integer"):
            service.submit_task(
                {
                    "task_type": "search_only",
                    "keywords": ["AI"],
                    "per_keyword_limit": 0,
                }
            )

    def test_direct_grab_normalizes_detail_urls_before_queuing_task(self):
        store = FakeTaskStore()
        service = make_service(store)

        service.submit_task(
            {
                "task_type": "direct_grab",
                "table_name": "gb_standards",
                "detail_urls": [
                    " http://STD.SAMR.GOV.CN/gb/search/gbDetailed?id=GB45438&from=test,",
                    "https://std.samr.gov.cn/gb/search/gbDetailed?id=GB45438",
                ],
            }
        )

        self.assertEqual(
            store.created_payload["detail_urls"],
            ["https://std.samr.gov.cn/gb/search/gbDetailed?id=GB45438"],
        )

    def test_task_item_pdf_path_cannot_escape_task_artifact_root(self):
        store = FakeTaskStore()
        service = make_service(store)
        task_id = "task-1"
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as file_obj:
            outside_pdf = file_obj.name
        self.addCleanup(lambda: os.path.exists(outside_pdf) and os.remove(outside_pdf))
        store.item = {"id": 1, "pdf_path": outside_pdf}

        artifact = service.get_task_item_pdf(task_id, 1)

        self.assertIsNone(artifact)


if __name__ == "__main__":
    unittest.main()
