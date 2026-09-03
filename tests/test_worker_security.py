import io
import json
import unittest

from app.worker_service import WorkerRequestHandler


def make_handler(body: bytes, content_type: str | None = "application/json"):
    handler = WorkerRequestHandler.__new__(WorkerRequestHandler)
    headers = {"Content-Length": str(len(body))}
    if content_type is not None:
        headers["Content-Type"] = content_type
    handler.headers = headers
    handler.rfile = io.BytesIO(body)
    return handler


class WorkerRequestSecurityTests(unittest.TestCase):
    def test_read_json_rejects_body_above_contract_limit(self):
        handler = make_handler(b"x" * (WorkerRequestHandler.MAX_REQUEST_BODY_BYTES + 1))

        with self.assertRaisesRegex(ValueError, "request body too large"):
            handler._read_json()

    def test_read_json_requires_json_content_type(self):
        handler = make_handler(json.dumps({"task_type": "search_only"}).encode(), "text/plain")

        with self.assertRaisesRegex(ValueError, "Content-Type must be application/json"):
            handler._read_json()

    def test_public_error_payload_does_not_include_internal_exception_text(self):
        payload = WorkerRequestHandler.public_error_payload(
            "internal_error",
            "database connection failed at mysql://secret-host",
        )

        self.assertEqual(payload["error"]["code"], "INTERNAL_ERROR")
        self.assertEqual(payload["error"]["message"], "internal server error")
        self.assertNotIn("secret-host", json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
