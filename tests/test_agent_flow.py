import tempfile
import unittest
import os
from pathlib import Path
from unittest.mock import patch

import config
from app.fake_executor import FakeCrawlerFactory, FakeSearchExecutor
from app.pipeline import PipelineRunner


class FakePipelineStore:
    def __init__(self, task):
        self.task = task
        self.items = []

    def get_task(self, task_id):
        return self.task if task_id == self.task["id"] else None

    def is_cancel_requested(self, task_id):
        return False

    def upsert_task_items(self, task_id, items, item_status="pending"):
        self.items = [dict(item, item_status=item_status) for item in items]

    def update_task_item(self, *args, **kwargs):
        return None


class AgentToolFlowTests(unittest.TestCase):
    def test_search_only_runs_through_injected_fake_tool_without_browser(self):
        task = {
            "id": "search-task",
            "task_type": "search_only",
            "request_payload": {"keywords": ["人工智能"], "per_keyword_limit": 1},
        }
        store = FakePipelineStore(task)
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            config, "get_base_dir", return_value=temp_dir
        ), patch.object(config, "update_config"), patch("app.pipeline.os.chdir", side_effect=AssertionError("pipeline must not change process cwd")):
            runner = PipelineRunner(
                store,
                search_executor=FakeSearchExecutor(
                    records=[
                        {
                            "detail_url": "https://std.samr.gov.cn/gb/search/gbDetailed?id=1",
                            "code": "GB/T 1-2020",
                            "name": "人工智能术语",
                            "keyword": "人工智能",
                            "status": "现行",
                        }
                    ]
                ),
                crawler_factory=FakeCrawlerFactory(),
            )

            result = runner.execute("search-task")

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["summary"]["total"], 1)
        self.assertEqual(store.items[0]["code"], "GB/T 1-2020")
        self.assertIn("run_evidence", result)
        self.assertIn("search", result["run_evidence"]["phases"])
        self.assertGreaterEqual(result["run_evidence"]["phases"]["search"]["duration_ms"], 0)

    def test_direct_grab_runs_through_fake_download_tool(self):
        task = {
            "id": "download-task",
            "task_type": "direct_grab",
            "request_payload": {
                "table_name": "gb_standards",
                "items": [
                    {
                        "detail_url": "https://std.samr.gov.cn/gb/search/gbDetailed?id=2",
                        "code": "GB/T 2-2020",
                        "name": "测试标准",
                    }
                ],
            },
        }
        store = FakePipelineStore(task)
        factory = FakeCrawlerFactory(scenario="success")
        original_cwd = os.getcwd()

        def remember_records(records, output_filename):
            factory.records = list(records)

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            config, "get_base_dir", return_value=temp_dir
        ), patch.object(config, "update_config"), patch("app.pipeline.os.chdir", side_effect=AssertionError("pipeline must not change process cwd")):
            runner = PipelineRunner(
                store,
                search_executor=FakeSearchExecutor(),
                crawler_factory=factory,
                excel_writer=remember_records,
            )

            result = runner.execute("download-task")

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["summary"]["succeeded"], 1)
        self.assertEqual(result["download_summary"]["pdf_saved"], 1)
        self.assertEqual(os.getcwd(), original_cwd)

    def test_direct_grab_reports_partial_failure_from_fake_download_tool(self):
        task = {
            "id": "partial-task",
            "task_type": "direct_grab",
            "request_payload": {
                "table_name": "gb_standards",
                "items": [
                    {"detail_url": "https://std.samr.gov.cn/gb/search/gbDetailed?id=3"},
                    {"detail_url": "https://std.samr.gov.cn/gb/search/gbDetailed?id=4"},
                ],
            },
        }
        store = FakePipelineStore(task)
        factory = FakeCrawlerFactory(scenario="partial")

        def remember_records(records, output_filename):
            factory.records = list(records)

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            config, "get_base_dir", return_value=temp_dir
        ), patch.object(config, "update_config"):
            runner = PipelineRunner(
                store,
                search_executor=FakeSearchExecutor(),
                crawler_factory=factory,
                excel_writer=remember_records,
            )

            result = runner.execute("partial-task")

        self.assertEqual(result["status"], "partial_failed")
        self.assertEqual(result["summary"]["succeeded"], 1)
        self.assertEqual(result["summary"]["failed"], 1)
        self.assertEqual(result["errors"][0]["error_code"], "SITE_TIMEOUT")


if __name__ == "__main__":
    unittest.main()
