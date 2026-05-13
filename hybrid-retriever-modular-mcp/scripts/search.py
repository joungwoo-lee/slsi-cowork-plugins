"""Hybrid search over local SQLite FTS5 and optional Qdrant vectors."""
from __future__ import annotations

from .config import Config
from .embedding_client import EmbeddingClient
from . import storage


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


def _rrf_scores(keyword_rows: list[dict], semantic_rows: list[dict], k: int) -> dict[str, float]:
    scores: dict[str, float] = {}
    for rank, row in enumerate(keyword_rows, 1):
        scores[row["chunk_id"]] = scores.get(row["chunk_id"], 0.0) + 1.0 / (k + rank)
    for rank, row in enumerate(semantic_rows, 1):
        scores[row["chunk_id"]] = scores.get(row["chunk_id"], 0.0) + 1.0 / (k + rank)
    return scores


def _metadata_match(metadata: dict, condition: dict | None) -> bool:
    if not condition:
        return True
    for key, expected in condition.items():
        actual = metadata.get(key)
        if isinstance(expected, list):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True


def hybrid_search(
    cfg: Config,
    query: str,
    dataset_ids: list[str],
    *,
    top: int = 12,
    top_k: int = 200,
    vector_similarity_weight: float | None = None,
    keyword: bool = True,
    fusion: str | None = None,
    parent_chunk_replace: bool | None = None,
    metadata_condition: dict | None = None,
) -> dict:
    keyword_rows: list[dict] = []
    semantic_rows: list[dict] = []

    with storage.sqlite_session(cfg) as conn:
        if keyword:
            keyword_rows = storage.fts_search(conn, query, dataset_ids, top_k)
        if cfg.embedding.api_url and cfg.embedding.dim > 0 and (vector_similarity_weight or 0.0) > 0.0:
            [vector] = EmbeddingClient(cfg.embedding).embed([query])
            qdrant = storage.open_qdrant(cfg)
            storage.ensure_collection(qdrant, cfg)
            semantic_rows = storage.vector_search(qdrant, cfg, vector, dataset_ids, top_k)

        kw_scores = _normalize_keyword(keyword_rows)
        sem_scores = _normalize_semantic(semantic_rows)
        all_ids = set(kw_scores) | set(sem_scores)
        chunks = storage.fetch_chunks(conn, list(all_ids))

    vector_weight = cfg.search.hybrid_alpha if vector_similarity_weight is None else max(0.0, min(1.0, vector_similarity_weight))
    fusion_mode = (fusion or cfg.search.fusion or "linear").lower()
    rrf = _rrf_scores(keyword_rows, semantic_rows, cfg.search.rrf_k) if fusion_mode == "rrf" else {}
    items: list[dict] = []
    for chunk_id in all_ids:
        chunk = chunks.get(chunk_id)
        if not chunk:
            continue
        if not _metadata_match(chunk.get("metadata", {}), metadata_condition):
            continue
        kw = kw_scores.get(chunk_id, 0.0)
        sem = sem_scores.get(chunk_id, 0.0)
        score = rrf.get(chunk_id, 0.0) if fusion_mode == "rrf" else (1.0 - vector_weight) * kw + vector_weight * sem
        replace_parent = cfg.search.parent_chunk_replace if parent_chunk_replace is None else parent_chunk_replace
        content = chunk.get("parent_content") if replace_parent and chunk.get("is_hierarchical") else chunk["content"]
        items.append({
            "id": chunk_id,
            "chunk_id": chunk_id,
            "dataset_id": chunk["dataset_id"],
            "document_id": chunk["document_id"],
            "document_name": chunk["document_name"],
            "position": chunk["position"],
            "content": content or chunk["content"],
            "child_content": chunk["content"],
            "parent_content": chunk.get("parent_content", ""),
            "parent_id": chunk.get("parent_id", 0),
            "child_id": chunk.get("child_id", chunk["position"]),
            "is_hierarchical": bool(chunk.get("is_hierarchical")),
            "is_contextual": bool(chunk.get("is_contextual")),
            "metadata": chunk.get("metadata", {}),
            "similarity": round(score, 6),
            "vector_similarity": round(sem, 6),
            "term_similarity": round(kw, 6),
        })
    items.sort(key=lambda item: item["similarity"], reverse=True)
    return {"total": len(items), "items": items[:top]}
