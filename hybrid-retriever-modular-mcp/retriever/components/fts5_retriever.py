"""SQLite FTS5 retriever component with Korean morpheme query rewriting.

Wraps ``storage.fts_search`` so it slots into a Haystack Pipeline. Output
documents carry ``score`` (BM25, lower = better in raw form, but we expose the
raw BM25 score so the downstream HybridJoiner can apply the same min-max
normalization the legacy ``search.hybrid_search`` used).
"""
from __future__ import annotations

from typing import List

from haystack import Document, component

from .. import storage
from ..config import Config


@component
class Fts5Retriever:
    """BM25 retrieval over the SQLite FTS5 chunk index."""

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg

    @component.output_types(documents=List[Document])
    def run(
        self,
        query: str,
        dataset_ids: List[str],
        top_k: int = 200,
        enabled: bool = True,
    ) -> dict:
        if not enabled or not query or not dataset_ids:
            return {"documents": []}
        with storage.sqlite_session(self._cfg) as conn:
            rows = storage.fts_search(conn, query, dataset_ids, top_k)
            chunk_ids = [r["chunk_id"] for r in rows]
            chunks = storage.fetch_chunks(conn, chunk_ids)
        docs: list[Document] = []
        for row in rows:
            chunk = chunks.get(row["chunk_id"])
            if not chunk:
                continue
            meta = _chunk_to_meta(chunk)
            meta["fts_rank"] = len(docs) + 1
            meta["fts_score"] = float(row["score"])
            docs.append(
                Document(
                    id=row["chunk_id"],
                    content=chunk["content"],
                    meta=meta,
                    score=float(row["score"]),
                )
            )
        return {"documents": docs}


def _chunk_to_meta(chunk: dict) -> dict:
    return {
        "dataset_id": chunk["dataset_id"],
        "document_id": chunk["document_id"],
        "document_name": chunk["document_name"],
        "position": int(chunk["position"]),
        "parent_content": chunk.get("parent_content", chunk["content"]),
        "parent_id": int(chunk.get("parent_id", 0)),
        "child_id": int(chunk.get("child_id", chunk["position"])),
        "is_hierarchical": bool(chunk.get("is_hierarchical")),
        "is_contextual": bool(chunk.get("is_contextual")),
        "metadata": chunk.get("metadata", {}) or {},
        "original_child_content": chunk.get("original_content", "") or chunk["content"],
    }
