"""Hybrid fusion component: byte-equivalent to the legacy ``hybrid_search``.

Implements both ``linear`` (min-max normalized weighted sum) and ``rrf``
(reciprocal rank fusion) modes, matching ``scripts.search`` numerics exactly.
Output documents carry score fields the response formatter needs:
``similarity``, ``term_similarity`` (keyword), ``vector_similarity``.
"""
from __future__ import annotations

from typing import List

from haystack import Document, component

from ..storage import metadata_matches


@component
class HybridJoiner:
    """Fuse keyword and semantic candidate sets into one ranked list.

    The fusion semantics match the legacy implementation:
        - ``linear``: scores per channel are min-max normalized, then combined
          as ``(1 - alpha) * keyword + alpha * vector``.
        - ``rrf``:    sum of 1/(k + rank) across channels, ignoring weights.
    """

    @component.output_types(documents=List[Document])
    def run(
        self,
        keyword_documents: List[Document],
        semantic_documents: List[Document] | None = None,
        graph_documents: List[Document] | None = None,
        fusion: str = "linear",
        vector_weight: float = 0.5,
        rrf_k: int = 60,
        metadata_condition: dict | None = None,
    ) -> dict:
        semantic_documents = semantic_documents or []
        graph_documents = graph_documents or []
        kw_rows = _docs_to_rows(keyword_documents, score_key="fts_score")
        sem_rows = _docs_to_rows(semantic_documents, score_key="vector_score")
        graph_rows = _docs_to_rows(graph_documents, score_key="graph_score")
        kw_scores = _normalize_keyword(kw_rows)
        sem_scores = _normalize_semantic(sem_rows)
        graph_scores = _normalize_generic(graph_rows)
        rrf_scores = _rrf_scores(kw_rows, sem_rows, graph_rows, rrf_k) if fusion == "rrf" else {}

        by_id: dict[str, Document] = {}
        for doc in list(keyword_documents) + list(semantic_documents) + list(graph_documents):
            if doc.id not in by_id:
                by_id[doc.id] = doc

        weight = max(0.0, min(1.0, float(vector_weight)))
        merged: list[Document] = []
        for chunk_id, doc in by_id.items():
            doc_meta = doc.meta or {}
            inner_meta = doc_meta.get("metadata") if isinstance(doc_meta.get("metadata"), dict) else {}
            merged_meta = {**inner_meta, **{k: v for k, v in doc_meta.items() if k != "metadata"}}
            if not metadata_matches(merged_meta, metadata_condition):
                continue
            kw = kw_scores.get(chunk_id, 0.0)
            sem = sem_scores.get(chunk_id, 0.0)
            graph_score = graph_scores.get(chunk_id, 0.0)
            if fusion == "rrf":
                score = rrf_scores.get(chunk_id, 0.0)
            else:
                score = (1.0 - weight) * kw + weight * sem + 0.2 * graph_score
            merged_doc = Document(
                id=doc.id,
                content=doc.content,
                meta={**doc.meta, "term_similarity": round(kw, 6), "vector_similarity": round(sem, 6), "graph_similarity": round(graph_score, 6)},
                score=round(score, 6),
            )
            merged.append(merged_doc)
        merged.sort(key=lambda d: d.score or 0.0, reverse=True)
        return {"documents": merged}


def _docs_to_rows(documents, score_key: str) -> list[dict]:
    rows = []
    for doc in documents:
        score = doc.meta.get(score_key)
        if score is None:
            score = doc.score
        rows.append({"chunk_id": doc.id, "score": float(score) if score is not None else 0.0})
    return rows


def _normalize_keyword(rows: list[dict]) -> dict[str, float]:
    if not rows:
        return {}
    vals = [(r["chunk_id"], -float(r["score"])) for r in rows]
    if len(vals) == 1:
        return {vals[0][0]: 1.0}
    lo, hi = min(v for _, v in vals), max(v for _, v in vals)
    spread = hi - lo or 1.0
    return {cid: (v - lo) / spread for cid, v in vals}


def _normalize_semantic(rows: list[dict]) -> dict[str, float]:
    return {r["chunk_id"]: max(0.0, min(1.0, (float(r["score"]) + 1.0) / 2.0)) for r in rows}


def _normalize_generic(rows: list[dict]) -> dict[str, float]:
    return {r["chunk_id"]: max(0.0, min(1.0, float(r["score"]))) for r in rows}


def _rrf_scores(keyword_rows: list[dict], semantic_rows: list[dict], graph_rows: list[dict], k: int) -> dict[str, float]:
    scores: dict[str, float] = {}
    for rank, row in enumerate(keyword_rows, 1):
        scores[row["chunk_id"]] = scores.get(row["chunk_id"], 0.0) + 1.0 / (k + rank)
    for rank, row in enumerate(semantic_rows, 1):
        scores[row["chunk_id"]] = scores.get(row["chunk_id"], 0.0) + 1.0 / (k + rank)
    for rank, row in enumerate(graph_rows, 1):
        scores[row["chunk_id"]] = scores.get(row["chunk_id"], 0.0) + 1.0 / (k + rank)
    return scores
