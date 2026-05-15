from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_server import handlers


class _DummyCfg:
    def __init__(self, data_root: Path):
        self.data_root = data_root


class EditorToolTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="editor_tool_"))
        self.cfg = _DummyCfg(self.tmpdir)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_current_status_reuses_live_editor(self) -> None:
        state_path = handlers._editor_state_path(self.cfg)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text('{"pid": 321, "port": 8765, "url": "http://127.0.0.1:8765"}', encoding="utf-8")

        with patch("mcp_server.handlers._probe_editor", return_value=True):
            status = handlers._current_editor_status(self.cfg)

        self.assertTrue(status["running"])
        self.assertEqual(status["url"], "http://127.0.0.1:8765")
        self.assertTrue(status["reused"])

    def test_open_pipeline_editor_returns_error_when_launch_fails(self) -> None:
        with patch("mcp_server.handlers.load_config", return_value=self.cfg), patch(
            "mcp_server.handlers._launch_pipeline_editor", side_effect=RuntimeError("boom")
        ):
            result = handlers.tool_open_pipeline_editor({})

        self.assertTrue(result["isError"])
        self.assertIn("Failed to open pipeline editor", result["content"][0]["text"])

    def test_close_pipeline_editor_reports_not_running(self) -> None:
        with patch("mcp_server.handlers.load_config", return_value=self.cfg):
            result = handlers.tool_close_pipeline_editor({})

        self.assertNotIn("isError", result)
        self.assertIn('"closed": false', result["content"][0]["text"].lower())


if __name__ == "__main__":
    unittest.main()
