from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pipeline_editor


class PipelineEditorPersistenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="pipeline_editor_"))
        self.orig_pipelines_dir = pipeline_editor.PIPELINES_DIR
        self.orig_user_profiles_path = pipeline_editor.USER_PROFILES_PATH
        pipeline_editor.PIPELINES_DIR = self.tmpdir / "pipelines"
        pipeline_editor.USER_PROFILES_PATH = self.tmpdir / "data" / "pipelines.json"

    def tearDown(self) -> None:
        pipeline_editor.PIPELINES_DIR = self.orig_pipelines_dir
        pipeline_editor.USER_PROFILES_PATH = self.orig_user_profiles_path
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_pipeline_writes_profile_and_topologies(self) -> None:
        payload = {
            "name": "custom_flow",
            "description": "editor save test",
            "indexing_overrides": {"skip_embedding": True},
            "retrieval_overrides": {},
            "search_kwargs": {"fusion": "rrf"},
            "indexing_topology": {
                "components": {
                    "loader": {
                        "type": "retriever.components.file_loader.LocalFileLoader",
                        "init_parameters": {"max_chars": 123},
                    }
                },
                "connections": [],
            },
            "retrieval_topology": {
                "components": {
                    "fts5": {
                        "type": "retriever.components.fts5_retriever.Fts5Retriever",
                        "init_parameters": {"data_root": ""},
                    }
                },
                "connections": [],
            },
        }

        result = pipeline_editor.save_pipeline(payload)
        self.assertEqual(result["status"], "ok")

        profiles = pipeline_editor._read_json(pipeline_editor.USER_PROFILES_PATH)
        self.assertIn("custom_flow", profiles)
        self.assertEqual(profiles["custom_flow"]["search_kwargs"], {"fusion": "rrf"})

        indexing_path = pipeline_editor.PIPELINES_DIR / "custom_flow_indexing.json"
        retrieval_path = pipeline_editor.PIPELINES_DIR / "custom_flow_retrieval.json"
        self.assertTrue(indexing_path.exists())
        self.assertTrue(retrieval_path.exists())
        indexing = pipeline_editor._read_json(indexing_path)
        retrieval = pipeline_editor._read_json(retrieval_path)
        self.assertIn("nodes", indexing)
        self.assertIn("nodes", retrieval)

    def test_load_pipeline_detail_returns_saved_topologies(self) -> None:
        pipeline_editor._atomic_write_json(
            pipeline_editor.USER_PROFILES_PATH,
            {
                "saved": {
                    "description": "saved pipeline",
                    "indexing_topology": "saved_indexing.json",
                    "retrieval_topology": "saved_retrieval.json",
                }
            },
        )
        pipeline_editor._atomic_write_json(
            pipeline_editor.PIPELINES_DIR / "saved_indexing.json",
            {"components": {"loader": {"type": "x", "init_parameters": {}}}, "connections": []},
        )
        pipeline_editor._atomic_write_json(
            pipeline_editor.PIPELINES_DIR / "saved_retrieval.json",
            {"components": {"joiner": {"type": "y", "init_parameters": {}}}, "connections": []},
        )

        detail = pipeline_editor.load_pipeline_detail("saved")
        self.assertEqual(detail["name"], "saved")
        self.assertEqual(detail["indexing"]["nodes"][0]["name"], "loader")
        self.assertEqual(detail["retrieval"]["nodes"][0]["name"], "joiner")

    def test_main_writes_and_clears_state_file(self) -> None:
        state_path = self.tmpdir / "editor-state.json"
        original_server = pipeline_editor.ThreadingHTTPServer

        class FakeServer:
            def __init__(self, addr, _handler):
                self.addr = addr

            def serve_forever(self):
                raise KeyboardInterrupt

            def server_close(self):
                return None

        pipeline_editor.ThreadingHTTPServer = FakeServer
        try:
            rc = pipeline_editor.main([
                "--port", "8765", "--no-browser", "--state-file", str(state_path)
            ])
        finally:
            pipeline_editor.ThreadingHTTPServer = original_server

        self.assertEqual(rc, 0)
        self.assertFalse(state_path.exists())


if __name__ == "__main__":
    unittest.main()
