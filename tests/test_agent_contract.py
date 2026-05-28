import unittest

from app.agent_contract import (
    annotate_errors,
    build_agent_status,
    classify_error_code,
    get_capabilities,
)


class AgentContractTests(unittest.TestCase):
    def test_capabilities_describe_agent_workflow(self):
        capabilities = get_capabilities()

        self.assertEqual(capabilities["api_version"], "2026-05-28")
        self.assertIn("search_only", capabilities["task_types"])
        self.assertIn("direct_grab", capabilities["task_types"])
        self.assertEqual(capabilities["recommended_workflow"], ["search_only", "direct_grab"])
        self.assertIn("search_results", capabilities["artifact_names"])

    def test_pending_status_tells_agent_to_poll(self):
        status = build_agent_status("search_only", "running", None, None)

        self.assertEqual(status["lifecycle"], "running")
        self.assertFalse(status["terminal"])
        self.assertEqual(status["outcome"], "pending")
        self.assertIn("poll_task", status["next_actions"])

    def test_search_only_with_items_returns_results_available(self):
        result_payload = {"summary": {"total": 2, "succeeded": 2, "failed": 0, "skipped": 0}}

        status = build_agent_status("search_only", "succeeded", result_payload, None)

        self.assertTrue(status["terminal"])
        self.assertEqual(status["outcome"], "results_available")
        self.assertFalse(status["retryable"])
        self.assertIn("select_items_for_direct_grab", status["next_actions"])

    def test_search_only_without_items_returns_no_results(self):
        result_payload = {"summary": {"total": 0, "succeeded": 0, "failed": 0, "skipped": 0}}

        status = build_agent_status("search_only", "succeeded", result_payload, None)

        self.assertEqual(status["outcome"], "no_results")
        self.assertIn("inspect_errors", status["next_actions"])

    def test_direct_grab_success_returns_downloaded(self):
        result_payload = {
            "summary": {"total": 1, "succeeded": 1, "failed": 0, "skipped": 0},
            "download_summary": {"pdf_saved": 1},
        }

        status = build_agent_status("direct_grab", "succeeded", result_payload, None)

        self.assertEqual(status["outcome"], "downloaded")
        self.assertIn("download_pdfs", status["next_actions"])

    def test_partial_grab_returns_partial_downloaded(self):
        result_payload = {
            "summary": {"total": 2, "succeeded": 1, "failed": 1, "skipped": 0},
            "errors": [{"message": "download failed: unable to resolve download request or save pdf"}],
        }

        status = build_agent_status("direct_grab", "partial_failed", result_payload, None)

        self.assertEqual(status["outcome"], "partial_downloaded")
        self.assertEqual(status["error_code"], "PDF_DOWNLOAD_FAILED")
        self.assertTrue(status["retryable"])

    def test_captcha_no_balance_is_machine_readable(self):
        self.assertEqual(
            classify_error_code("captcha recognize failed: 无可用题分"),
            "CAPTCHA_NO_BALANCE",
        )

        status = build_agent_status(
            "direct_grab",
            "failed",
            {"summary": {"total": 1, "succeeded": 0, "failed": 1}, "errors": [{"message": "captcha recognize failed: 无可用题分"}]},
            None,
        )

        self.assertEqual(status["outcome"], "blocked_captcha")
        self.assertEqual(status["error_code"], "CAPTCHA_NO_BALANCE")
        self.assertIn("fix_captcha_account", status["next_actions"])

    def test_not_public_is_not_retryable(self):
        self.assertEqual(
            classify_error_code("view text button not found: //*[contains(@class, 'openpdf')]"),
            "NO_PUBLIC_TEXT",
        )

        errors = annotate_errors(
            [{"detail_url": "https://example.test/detail", "message": "standard not public: copyright restricted"}]
        )

        self.assertEqual(errors[0]["error_code"], "NO_PUBLIC_TEXT")
        self.assertFalse(errors[0]["retryable"])

    def test_database_error_maps_to_db_write_failed(self):
        self.assertEqual(classify_error_code("database write failed: duplicate key"), "DB_WRITE_FAILED")

    def test_invalid_input_maps_to_invalid_input(self):
        self.assertEqual(classify_error_code("table_name is required"), "INVALID_INPUT")


if __name__ == "__main__":
    unittest.main()
