from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from mcp_server.catalog import TOOLS
from mcp_server.dispatch import canonical_tool_name, handle_tools_call


ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("EMAIL_MCP_ENV", str(ROOT / "test" / "test.env"))


class DispatchTests(unittest.TestCase):
    def test_list_mails_description_warns_against_whitespace(self) -> None:
        description = next(tool["description"] for tool in TOOLS if tool["name"] == "list_mails")
        self.assertIn("exact tool name `list_mails`", description)
        self.assertIn("never insert whitespace", description)

    def test_canonical_tool_name_strips_namespace_and_whitespace(self) -> None:
        self.assertEqual(canonical_tool_name("email_mcp_list_ mails"), "list_mails")
        self.assertEqual(canonical_tool_name("  list_mails  "), "list_mails")

    def test_tools_call_accepts_wrapped_namespaced_tool_name(self) -> None:
        result = handle_tools_call(
            {
                "name": "email_mcp_list_ mails",
                "arguments": {"limit": 2, "offset": 0},
            }
        )

        self.assertNotIn("isError", result)
        payload = json.loads(result["content"][0]["text"])
        self.assertEqual(payload["returned"], 2)
        self.assertEqual(payload["limit"], 2)


if __name__ == "__main__":
    unittest.main()
