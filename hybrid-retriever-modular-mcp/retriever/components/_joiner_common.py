from __future__ import annotations

from haystack import Document

from ..storage import metadata_matches


def docs_to_rows(documents: list[Document], score_key: str) -> list[dict]:
    rows = []
    for doc in documents:
        score = doc.meta.get(score_key)
        if score is None:
            score = doc.score
        rows.append({"chunk_id": doc.id, "score": float(score) if score is not None else 0.0})
    return rows


def normalize_keyword(rows: list[dict]) -> dict[str, float]:
    if not rows:
        return {}
    vals = [(r["chunk_id"], -float(r["score"])) for r in rows]
    if len(vals) == 1:
        return {vals[0][0]: 1.0}
    lo, hi = min(v for _, v in vals), max(v for _, v in vals)
    spread = hi - lo or 1.0
    return {cid: (v - lo) / spread for cid, v in vals}


def normalize_semantic(rows: list[dict]) -> dict[str, float]:
    return {r["chunk_id"]: max(0.0, min(1.0, (float(r["score"]) + 1.0) / 2.0)) for r in rows}


def normalize_generic(rows: list[dict]) -> dict[str, float]:
    return {r["chunk_id"]: max(0.0, min(1.0, float(r["score"]))) for r in rows}


def rrf_scores(keyword_rows: list[dict], semantic_rows: list[dict], graph_rows: list[dict], k: int) -> dict[str, float]:
    scores: dict[str, float] = {}
    for rank, row in enumerate(keyword_rows, 1):
        scores[row["chunk_id"]] = scores.get(row["chunk_id"], 0.0) + 1.0 / (k + rank)
    for rank, row in enumerate(semantic_rows, 1):
        scores[row["chunk_id"]] = scores.get(row["chunk_id"], 0.0) + 1.0 / (k + rank)
    for rank, row in enumerate(graph_rows, 1):
        scores[row["chunk_id"]] = scores.get(row["chunk_id"], 0.0) + 1.0 / (k + rank)
    return scores


def merged_documents(
    keyword_documents: list[Document],
    semantic_documents: list[Document],
    graph_documents: list[Document],
    metadata_condition: dict | None,
) -> list[Document]:
    by_id: dict[str, Document] = {}
    for doc in keyword_documents + semantic_documents + graph_documents:
        if doc.id not in by_id:
            by_id[doc.id] = doc

    merged: list[Document] = []
    for doc in by_id.values():
        doc_meta = doc.meta or {}
        inner_meta = doc_meta.get("metadata") if isinstance(doc_meta.get("metadata"), dict) else {}
        flattened_meta = {**inner_meta, **{k: v for k, v in doc_meta.items() if k != "metadata"}}
        if metadata_matches(flattened_meta, metadata_condition):
            merged.append(doc)
    return merged
