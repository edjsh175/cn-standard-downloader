import unittest

from app.agent_contract import get_capabilities
from app.tool_contract import get_tool_contract


class ToolContractTests(unittest.TestCase):
    def test_contract_describes_agent_callable_tools_and_limits(self):
        contract = get_tool_contract()

        self.assertEqual(contract["contract_version"], "1.0.0")
        self.assertEqual(
            {tool["name"] for tool in contract["tools"]},
            {
                "search_standards",
                "download_standards",
                "get_task_status",
                "get_task_result",
                "cancel_task",
                "get_artifact",
            },
        )
        self.assertGreater(contract["limits"]["max_request_body_bytes"], 0)
        self.assertIn("CAPTCHA_NO_BALANCE", contract["error_catalog"])
        for tool in contract["tools"]:
            self.assertIn("input_schema", tool)
            self.assertEqual(tool["input_schema"]["type"], "object")
        self.assertEqual(
            contract["artifact_schema"]["required"],
            ["name", "content_type", "size_bytes", "sha256"],
        )

    def test_capabilities_expose_the_same_contract_without_second_tool_list(self):
        contract = get_tool_contract()
        capabilities = get_capabilities()

        self.assertEqual(capabilities["contract_version"], contract["contract_version"])
        self.assertEqual(capabilities["tools"], contract["tools"])
        self.assertEqual(capabilities["limits"], contract["limits"])
        self.assertEqual(capabilities["error_catalog"], contract["error_catalog"])


if __name__ == "__main__":
    unittest.main()
