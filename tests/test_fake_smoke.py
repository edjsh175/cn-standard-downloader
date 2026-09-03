import unittest
import json
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from scripts.ai_worker_smoke import main, run_fake_flow


class FakeSmokeTests(unittest.TestCase):
    def test_fake_flow_reports_search_and_download_contract_outcomes(self):
        report = run_fake_flow()

        self.assertEqual(report["search"]["agent_status"]["outcome"], "results_available")
        self.assertEqual(report["download"]["agent_status"]["outcome"], "downloaded")
        self.assertEqual(report["download"]["summary"]["succeeded"], 1)

    def test_fake_flow_cli_does_not_require_running_worker(self):
        output = StringIO()
        with patch("sys.argv", ["ai_worker_smoke.py", "--token", "test-worker-token", "--fake-flow"]), redirect_stdout(output):
            main()

        report = json.loads(output.getvalue())
        self.assertIn("fake_flow", report["checks"])


if __name__ == "__main__":
    unittest.main()
