import http.client
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import config
from app.worker_service import TaskWorkerService, WorkerRequestHandler


class FakeTaskStore:
    def __init__(self):
        self.created_task_type = None
        self.created_payload = None
        self.item = None
        self.result_payload = None
        self.items = []
        self.status = "pending"

    def create_task(self, task_type, payload):
        self.created_task_type = task_type
        self.created_payload = dict(payload)
        return "task-1"

    def get_task(self, task_id):
        return {
            "id": task_id,
            "task_type": self.created_task_type,
            "status": self.status,
            "table_name": (self.created_payload or {}).get("table_name", ""),
            "request_payload": self.created_payload,
            "result_payload": self.result_payload,
            "error_message": None,
            "cancel_requested": False,
            "created_at": "2026-05-25T00:00:00",
            "started_at": None,
            "finished_at": None,
            "updated_at": "2026-05-25T00:00:00",
        }

    def get_task_item(self, task_id, item_id):
        return self.item

    def list_task_items(self, task_id):
        return list(self.items)


class FakeHttpService:
    def get_capabilities(self):
        return {
            "api_version": "2026-05-28",
            "task_types": ["search_only", "direct_grab", "keyword_search"],
            "terminal_states": ["succeeded", "failed", "partial_failed", "cancelled"],
            "artifact_names": ["search_results", "failed_results", "log_file"],
            "recommended_workflow": ["search_only", "direct_grab"],
        }

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

    def test_capabilities_requires_bearer_token(self):
        status, payload = self.request("GET", "/api/capabilities")

        self.assertEqual(status, 401)
        self.assertEqual(payload, {"error": "unauthorized"})

    def test_capabilities_with_bearer_token_returns_agent_contract_metadata(self):
        status, payload = self.request(
            "GET",
            "/api/capabilities",
            headers={"Authorization": "Bearer secret-token"},
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["api_version"], "2026-05-28")
        self.assertEqual(payload["recommended_workflow"], ["search_only", "direct_grab"])
        self.assertIn("search_results", payload["artifact_names"])


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

    def test_search_only_rejects_more_keywords_than_agent_contract_limit(self):
        service = make_service()

        with self.assertRaisesRegex(ValueError, "keywords must contain at most 50 items"):
            service.submit_task(
                {
                    "task_type": "search_only",
                    "keywords": [f"keyword-{index}" for index in range(51)],
                }
            )

    def test_direct_grab_rejects_more_items_than_agent_contract_limit(self):
        service = make_service()

        with self.assertRaisesRegex(ValueError, "items must contain at most 500 items"):
            service.submit_task(
                {
                    "task_type": "direct_grab",
                    "items": [
                        {"detail_url": f"https://std.samr.gov.cn/gb/search/gbDetailed?id={index}"}
                        for index in range(501)
                    ],
                }
            )

    def test_submit_task_attaches_agent_status(self):
        store = FakeTaskStore()
        service = make_service(store)

        task = service.submit_task(
            {
                "task_type": "search_only",
                "keywords": ["AI"],
                "per_keyword_limit": 1,
            }
        )

        self.assertEqual(task["agent_status"]["outcome"], "pending")
        self.assertIn("poll_task", task["agent_status"]["next_actions"])

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

    def test_get_task_attaches_agent_status(self):
        store = FakeTaskStore()
        store.created_task_type = "search_only"
        store.created_payload = {"task_type": "search_only", "keywords": ["AI"]}
        store.status = "succeeded"
        store.result_payload = {"summary": {"total": 1, "succeeded": 1, "failed": 0, "skipped": 0}}
        service = make_service(store)

        task = service.get_task("task-1")

        self.assertEqual(task["agent_status"]["outcome"], "results_available")
        self.assertIn("select_items_for_direct_grab", task["agent_status"]["next_actions"])

    def test_get_task_result_attaches_agent_status_and_error_codes(self):
        store = FakeTaskStore()
        store.created_task_type = "direct_grab"
        store.created_payload = {"task_type": "direct_grab", "table_name": "gb_standards"}
        store.status = "failed"
        store.result_payload = {
            "summary": {"total": 1, "succeeded": 0, "failed": 1, "skipped": 0},
            "errors": [
                {
                    "detail_url": "https://std.samr.gov.cn/gb/search/gbDetailed?id=GB1",
                    "message": "captcha recognize failed: 无可用题分",
                }
            ],
        }
        service = make_service(store)

        result = service.get_task_result("task-1")

        self.assertEqual(result["agent_status"]["outcome"], "blocked_captcha")
        self.assertEqual(result["result"]["errors"][0]["error_code"], "CAPTCHA_NO_BALANCE")
        self.assertTrue(result["result"]["errors"][0]["retryable"])

    def test_result_exposes_artifact_integrity_metadata_without_local_path(self):
        store = FakeTaskStore()
        service = make_service(store)
        with tempfile.TemporaryDirectory() as temp_dir:
            artifact_root = os.path.join(temp_dir, "artifacts", "tasks", "task-1")
            os.makedirs(artifact_root)
            search_path = os.path.join(artifact_root, "search_results.xlsx")
            with open(search_path, "wb") as stream:
                stream.write(b"search-result-artifact")

            with patch.object(config, "get_base_dir", return_value=temp_dir):
                result = service._attach_result_urls(
                    "task-1",
                    {"artifacts": {"search_results": search_path}},
                )

        metadata = result["artifact_metadata"]["search_results"]
        self.assertEqual(metadata["name"], "search_results")
        self.assertGreater(metadata["size_bytes"], 0)
        self.assertNotIn("path", metadata)


if __name__ == "__main__":
    unittest.main()
