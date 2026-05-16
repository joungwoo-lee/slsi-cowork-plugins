"""Tests for the split joiner components."""
from __future__ import annotations

import unittest

from haystack import Document

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retriever.components.linear_joiner import LinearJoiner
from retriever.components.rrf_joiner import RrfJoiner


def _kw_doc(chunk_id: str, score: float, meta: dict | None = None) -> Document:
    base = {"fts_score": score}
    base.update(meta or {})
    return Document(id=chunk_id, content="kw " + chunk_id, meta=base, score=score)


def _sem_doc(chunk_id: str, score: float, meta: dict | None = None) -> Document:
    base = {"vector_score": score}
    base.update(meta or {})
    return Document(id=chunk_id, content="sem " + chunk_id, meta=base, score=score)


def _graph_doc(chunk_id: str, score: float, meta: dict | None = None) -> Document:
    base = {"graph_score": score}
    base.update(meta or {})
    return Document(id=chunk_id, content="graph " + chunk_id, meta=base, score=score)


class RrfJoinerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.j = RrfJoiner()

    def test_rrf_first_rank_score(self) -> None:
        out = self.j.run(
            keyword_documents=[_kw_doc("a", 0.0)],
            semantic_documents=[],
            rrf_k=60,
        )
        self.assertEqual(len(out["documents"]), 1)
        # RRF rank-1 with k=60 is 1/61.
        self.assertAlmostEqual(out["documents"][0].score, round(1.0 / 61, 6), places=5)

    def test_rrf_accepts_graph_branch(self) -> None:
        out = self.j.run(
            keyword_documents=[_kw_doc("a", -5.0)],
            semantic_documents=[],
            graph_documents=[_graph_doc("b", 0.8)],
            rrf_k=60,
        )
        self.assertEqual([d.id for d in out["documents"]], ["a", "b"])
        self.assertEqual(out["documents"][1].meta["graph_similarity"], 0.8)


class LinearJoinerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.j = LinearJoiner()

    def test_linear_pure_keyword_when_weight_zero(self) -> None:
        out = self.j.run(
            keyword_documents=[_kw_doc("a", -5.0), _kw_doc("b", -2.0)],
            semantic_documents=[],
            vector_weight=0.0,
        )
        # keyword side normalizes -BM25, so the lower (more negative) score is the better doc.
        ids = [d.id for d in out["documents"]]
        self.assertEqual(ids[0], "a")

    def test_metadata_condition_filters_results(self) -> None:
        out = self.j.run(
            keyword_documents=[
                _kw_doc("a", 0.0, {"dataset_id": "ds1", "metadata": {"y": 2024}}),
                _kw_doc("b", 0.0, {"dataset_id": "ds2", "metadata": {"y": 2025}}),
            ],
            semantic_documents=[],
            vector_weight=0.0,
            metadata_condition={"y": 2025},
        )
        self.assertEqual([d.id for d in out["documents"]], ["b"])

    def test_metadata_condition_top_level_key(self) -> None:
        # dataset_id lives at the top of Document.meta, not under "metadata".
        # The joiner must merge both layers before evaluating.
        out = self.j.run(
            keyword_documents=[
                _kw_doc("a", 0.0, {"dataset_id": "ds1"}),
                _kw_doc("b", 0.0, {"dataset_id": "ds2"}),
            ],
            semantic_documents=[],
            vector_weight=0.0,
            metadata_condition={"dataset_id": "ds2"},
        )
        self.assertEqual([d.id for d in out["documents"]], ["b"])


if __name__ == "__main__":
    unittest.main()
