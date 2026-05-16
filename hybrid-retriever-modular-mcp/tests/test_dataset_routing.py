from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_server import handlers
from mcp_server.catalog import build_tools
from retriever import storage
from retriever.config import Config


def _payload(tool_result: dict) -> dict:
    text = tool_result["content"][0]["text"]
    return json.loads(text)


class DatasetRoutingTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.cfg = Config(data_root=Path(self._tmp.name))
        self.cfg.ensure_dirs()
        self._old_load_config = handlers.load_config
        self._old_data_root_env = os.environ.get("RETRIEVER_DATA_ROOT")
        os.environ["RETRIEVER_DATA_ROOT"] = str(self.cfg.data_root)
        handlers.load_config = lambda: self.cfg

    def tearDown(self) -> None:
        handlers.load_config = self._old_load_config
        if self._old_data_root_env is None:
            os.environ.pop("RETRIEVER_DATA_ROOT", None)
        else:
            os.environ["RETRIEVER_DATA_ROOT"] = self._old_data_root_env
        self._tmp.cleanup()

    def test_get_dataset_exposes_metadata(self) -> None:
        with storage.sqlite_session(self.cfg) as conn:
            storage.ensure_dataset(conn, "demo", "demo")
            storage.update_dataset_metadata(conn, "demo", {"preferred_search_pipeline": "hipporag"})
        result = handlers.tool_get_dataset({"dataset_id": "demo"})
        body = _payload(result)
        self.assertEqual(body["metadata"]["preferred_search_pipeline"], "hipporag")

    def test_search_auto_routes_to_hipporag(self) -> None:
        with storage.sqlite_session(self.cfg) as conn:
            storage.ensure_dataset(conn, "demo", "demo")
            storage.update_dataset_metadata(conn, "demo", {"preferred_search_pipeline": "hipporag"})

        old_hippo = handlers.hipporag_query.search
        old_hybrid = handlers.retriever_api.hybrid_search

        class Result:
            query_entities = ["samsung"]
            chunks = [{
                "chunk_id": "doc:0",
                "dataset_id": "demo",
                "document_id": "doc",
                "document_name": "doc.txt",
                "position": 0,
                "content": "Samsung is in Seoul",
                "score": 1.0,
                "matched_entities": ["e1"],
            }]

        try:
            handlers.hipporag_query.search = lambda *args, **kwargs: Result()

            def fail_hybrid(*args, **kwargs):
                raise AssertionError("hybrid_search should not be called")

            handlers.retriever_api.hybrid_search = fail_hybrid
            result = handlers.tool_search({"query": "samsung", "dataset_ids": ["demo"]})
            body = _payload(result)
            self.assertEqual(body["search_pipeline"], "hipporag")
            self.assertEqual(body["total"], 1)
        finally:
            handlers.hipporag_query.search = old_hippo
            handlers.retriever_api.hybrid_search = old_hybrid

    def test_search_falls_back_to_default_for_mixed_datasets(self) -> None:
        with storage.sqlite_session(self.cfg) as conn:
            storage.ensure_dataset(conn, "a", "a")
            storage.ensure_dataset(conn, "b", "b")
            storage.update_dataset_metadata(conn, "a", {"preferred_search_pipeline": "hipporag"})
            storage.update_dataset_metadata(conn, "b", {"preferred_search_pipeline": "default"})

        old_hippo = handlers.hipporag_query.search
        old_hybrid = handlers.retriever_api.hybrid_search
        try:
            def fake_hybrid(*args, **kwargs):
                return {"items": [], "total": 0}

            def fail_hippo(*args, **kwargs):
                raise AssertionError("hipporag_search should not be called")

            handlers.retriever_api.hybrid_search = fake_hybrid
            handlers.hipporag_query.search = fail_hippo
            result = handlers.tool_search({"query": "x", "dataset_ids": ["a", "b"]})
            body = _payload(result)
            self.assertEqual(body["search_pipeline"], "default")
        finally:
            handlers.hipporag_query.search = old_hippo
            handlers.retriever_api.hybrid_search = old_hybrid

    def test_create_dataset_records_use_when(self) -> None:
        result = handlers.tool_create_dataset({
            "name": "demo dataset",
            "use_when": "Use for finance policy questions.",
        })
        body = _payload(result)
        self.assertEqual(body["metadata"]["use_when"], "Use for finance policy questions.")
        ds = handlers.tool_get_dataset({"dataset_id": body["id"]})
        ds_body = _payload(ds)
        self.assertEqual(ds_body["metadata"]["use_when"], "Use for finance policy questions.")

    def test_build_tools_includes_dataset_use_when(self) -> None:
        with storage.sqlite_session(self.cfg) as conn:
            storage.ensure_dataset(conn, "finance", "finance")
            storage.update_dataset_metadata(conn, "finance", {"use_when": "Use for finance policy questions."})
        tools = {tool["name"]: tool for tool in build_tools()}
        search_desc = tools["search"]["inputSchema"]["properties"]["dataset_ids"]["description"]
        upload_desc = tools["upload"]["inputSchema"]["properties"]["dataset_id"]["description"]
        self.assertIn("finance", search_desc)
        self.assertIn("Use for finance policy questions.", search_desc)
        self.assertIn("finance", upload_desc)

    def test_search_and_upload_do_not_expose_pipeline_param(self) -> None:
        tools = {tool["name"]: tool for tool in build_tools()}
        self.assertNotIn("pipeline", tools["search"]["inputSchema"]["properties"])
        self.assertIn("pipeline", tools["upload"]["inputSchema"]["properties"])

    def test_admin_tools_are_hidden_from_public_catalog(self) -> None:
        tools = {tool["name"]: tool for tool in build_tools()}
        self.assertIn("admin_help", tools)
        self.assertNotIn("get_job", tools)
        self.assertNotIn("create_dataset", tools)
        self.assertNotIn("health", tools)
        self.assertNotIn("graph_query", tools)
        self.assertNotIn("list_pipelines", tools)
        self.assertNotIn("graph_rebuild", tools)
        self.assertNotIn("hipporag_index", tools)

    def test_admin_help_lists_hidden_tools(self) -> None:
        result = handlers.tool_admin_help({})
        body = _payload(result)
        names = [item["name"] for item in body["admin_tools"]]
        self.assertIn("graph_rebuild", names)
        self.assertIn("list_pipelines", names)


if __name__ == "__main__":
    unittest.main()
