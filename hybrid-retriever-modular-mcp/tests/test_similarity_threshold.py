"""``similarity_threshold`` must propagate handlers → api → engine.

Two layers worth pinning with unit tests:

1. The handler clamps and forwards the value (a NaN or out-of-range threshold
   must not silently disable filtering or drop every result).
2. ``run_retrieval`` actually applies the floor to the final document list
   BEFORE ``top_n`` slicing, so callers either get strong matches or none.

End-to-end behavior over MCP stdio is exercised by ``scripts_test/e2e_stdio.py``.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class HandlerClampsAndForwardsThresholdTest(unittest.TestCase):
    def _run_search(self, threshold_arg) -> float:
        """Invoke tool_search with a single arg combo and return the threshold
        that reached ``retriever_api.hybrid_search``."""
        from mcp_server import handlers

        captured: dict = {}

        def fake_hybrid_search(*args, **kwargs):
            captured["similarity_threshold"] = kwargs.get("similarity_threshold")
            return {"total": 0, "items": []}

        with mock.patch.object(handlers.retriever_api, "hybrid_search", side_effect=fake_hybrid_search), \
             mock.patch.object(handlers, "_dataset_search_pipeline", return_value="default"), \
             mock.patch.object(handlers, "load_config", return_value=SimpleNamespace()):
            handlers.tool_search({
                "query": "x",
                "dataset_ids": ["ds"],
                "similarity_threshold": threshold_arg,
            })
        return captured["similarity_threshold"]

    def test_valid_threshold_forwarded_verbatim(self) -> None:
        self.assertEqual(self._run_search(0.42), 0.42)

    def test_zero_default_when_missing(self) -> None:
        from mcp_server import handlers

        captured: dict = {}

        def fake_hybrid_search(*args, **kwargs):
            captured["similarity_threshold"] = kwargs.get("similarity_threshold")
            return {"total": 0, "items": []}

        with mock.patch.object(handlers.retriever_api, "hybrid_search", side_effect=fake_hybrid_search), \
             mock.patch.object(handlers, "_dataset_search_pipeline", return_value="default"), \
             mock.patch.object(handlers, "load_config", return_value=SimpleNamespace()):
            handlers.tool_search({"query": "x", "dataset_ids": ["ds"]})
        self.assertEqual(captured["similarity_threshold"], 0.0)

    def test_out_of_range_clamped_to_unit_interval(self) -> None:
        self.assertEqual(self._run_search(1.5), 1.0)
        self.assertEqual(self._run_search(-0.3), 0.0)

    def test_garbage_threshold_silently_disables_filter(self) -> None:
        # Better to disable the filter than to error out the whole search.
        self.assertEqual(self._run_search("not-a-number"), 0.0)
        self.assertEqual(self._run_search(None), 0.0)


class ApiForwardsThresholdToEngineTest(unittest.TestCase):
    def test_hybrid_search_passes_threshold_through(self) -> None:
        from retriever import api as retriever_api

        captured: dict = {}

        def fake_run_retrieval(cfg, query, dataset_ids, **kwargs):
            captured.update(kwargs)
            return {"total": 0, "items": []}

        with mock.patch.object(retriever_api, "run_retrieval", side_effect=fake_run_retrieval), \
             mock.patch.object(retriever_api, "select_retrieval", return_value={"top_n": 12, "top_k": 200}), \
             mock.patch.object(retriever_api.profiles, "sync_with_disk"), \
             mock.patch.object(retriever_api.profiles, "get",
                               return_value=SimpleNamespace(
                                   retrieval_overrides={}, search_kwargs={},
                               )):
            retriever_api.hybrid_search(
                cfg=SimpleNamespace(),
                query="q",
                dataset_ids=["ds"],
                pipeline="default",
                similarity_threshold=0.7,
            )
        self.assertEqual(captured.get("similarity_threshold"), 0.7)


class EngineFiltersDocsBelowThresholdTest(unittest.TestCase):
    """Validate that run_retrieval applies the threshold BEFORE top_n slicing.

    Builds a Haystack-shaped output stub and patches both ``_load_pipeline``
    and the injected runtime so the threshold-application code path can be
    exercised without a real index.
    """

    def test_threshold_drops_low_scored_docs_then_takes_top_n(self) -> None:
        from retriever.pipelines import engine

        class _Doc:
            __slots__ = ("id", "content", "score", "meta")
            def __init__(self, score: float) -> None:
                self.id = f"doc-{score}"
                self.content = "stub"
                self.score = score
                self.meta = {"document_id": "d", "document_name": "n", "position": 0}

        # 5 docs sorted desc by score: 0.9, 0.7, 0.5, 0.3, 0.1
        docs = [_Doc(s) for s in (0.9, 0.7, 0.5, 0.3, 0.1)]

        class _StubPipeline:
            graph = SimpleNamespace(nodes={})
            def inputs(self):  # noqa: D401 - haystack-compatible shim
                return {}
            def run(self, _inputs, include_outputs_from=None):
                return {"parent": {"documents": docs}}

        with mock.patch.object(engine, "_load_pipeline", return_value=_StubPipeline()), \
             mock.patch.object(engine, "_inject_retrieval_runtime"):
            out = engine.run_retrieval(
                cfg=SimpleNamespace(embedding=None),
                query="q",
                dataset_ids=["ds"],
                retrieval_opts={"top_n": 10, "top_k": 100},
                similarity_threshold=0.6,
            )

        # Only 0.9 and 0.7 survive the 0.6 floor.
        self.assertEqual(out["total"], 2)
        self.assertEqual(len(out["items"]), 2)
        self.assertAlmostEqual(out["items"][0]["similarity"], 0.9)
        self.assertAlmostEqual(out["items"][1]["similarity"], 0.7)


if __name__ == "__main__":
    unittest.main()
