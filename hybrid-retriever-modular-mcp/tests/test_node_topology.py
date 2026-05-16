from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retriever.pipelines import editor_store, engine


class NodeTopologyTest(unittest.TestCase):
    def test_topology_for_ui_returns_node_centric_for_standard_json(self) -> None:
        raw = {
            "components": {
                "joiner": {"type": "x.Joiner", "init_parameters": {}},
                "parent": {"type": "x.Parent", "init_parameters": {}},
            },
            "connections": [{"sender": "joiner.documents", "receiver": "parent.documents"}],
        }

        topo = editor_store.topology_for_ui(raw)
        self.assertIn("nodes", topo)
        self.assertEqual(topo["nodes"][1]["inputs"][0]["from"], "joiner.documents")

    def test_runtime_loader_accepts_node_centric_json(self) -> None:
        tmpdir = Path(tempfile.mkdtemp(prefix="node_topology_"))
        original_dir = engine.PIPELINES_DIR
        engine.PIPELINES_DIR = tmpdir
        try:
            path = tmpdir / "sample.json"
            path.write_text(
                json.dumps(
                    {
                        "nodes": [
                            {
                                "name": "query_embedder",
                                "module": "retriever.components.document_embedder.HttpTextEmbedder",
                                "params": {
                                    "api_url": "",
                                    "api_key": "",
                                    "model": "",
                                    "dim": 0,
                                    "x_dep_ticket": "",
                                    "x_system_name": "hybrid-retriever-modular-mcp",
                                    "batch_size": 16,
                                    "timeout_sec": 60,
                                    "verify_ssl": False,
                                },
                            },
                            {
                                "name": "vector",
                                "module": "retriever.components.vector_retriever.LocalQdrantRetriever",
                                "params": {"data_root": "", "collection": "retriever_chunks"},
                                "inputs": [{"port": "embedding", "from": "query_embedder.embedding"}],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            pipeline = engine._load_pipeline("sample.json")
            self.assertIn("query_embedder", pipeline.graph.nodes)
            self.assertIn("vector", pipeline.graph.nodes)
        finally:
            engine.PIPELINES_DIR = original_dir
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_keyword_only_topology_has_no_vector_nodes(self) -> None:
        pipeline = engine._load_pipeline("keyword_only_unified.json")

        self.assertNotIn("embedder", pipeline.graph.nodes)
        self.assertNotIn("qdrant_writer", pipeline.graph.nodes)
        self.assertNotIn("query_embedder", pipeline.graph.nodes)
        self.assertNotIn("vector", pipeline.graph.nodes)

    def test_all_shipped_pipelines_use_rrf_joiner(self) -> None:
        pipelines_dir = Path(__file__).resolve().parent.parent / "retriever" / "pipelines"
        for name in [
            "default_unified.json",
            "email_unified.json",
            "hippo2_graph_rrf_unified.json",
            "keyword_only_unified.json",
            "rrf_graph_rerank_unified.json",
            "rrf_llm_rerank_retrieval.json",
            "rrf_llm_rerank_unified.json",
            "rrf_rerank_retrieval.json",
            "rrf_rerank_unified.json",
        ]:
            raw = json.loads((pipelines_dir / name).read_text("utf-8"))
            joiner = next(node for node in raw["nodes"] if node["name"] == "joiner")
            self.assertEqual(joiner["module"], "retriever.components.rrf_joiner.RrfJoiner", name)


if __name__ == "__main__":
    unittest.main()
