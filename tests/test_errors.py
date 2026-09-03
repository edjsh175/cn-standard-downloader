import unittest

from app.agent_contract import annotate_errors
from app.errors import ErrorCode, WorkerError


class WorkerErrorTests(unittest.TestCase):
    def test_worker_error_serializes_machine_readable_context(self):
        error = WorkerError(
            ErrorCode.SITE_TIMEOUT,
            "upstream request timed out",
            detail_url="https://std.samr.gov.cn/detail?id=1",
        )

        self.assertEqual(
            error.to_dict(),
            {
                "detail_url": "https://std.samr.gov.cn/detail?id=1",
                "error_code": "SITE_TIMEOUT",
                "retryable": True,
                "category": "upstream",
                "message": "upstream request timed out",
            },
        )

    def test_explicit_error_code_wins_over_legacy_message_inference(self):
        errors = annotate_errors(
            [{
                "error_code": "DB_WRITE_FAILED",
                "message": "captcha page was not available",
            }]
        )

        self.assertEqual(errors[0]["error_code"], "DB_WRITE_FAILED")
        self.assertFalse(errors[0]["retryable"])
        self.assertEqual(errors[0]["category"], "persistence")


if __name__ == "__main__":
    unittest.main()
