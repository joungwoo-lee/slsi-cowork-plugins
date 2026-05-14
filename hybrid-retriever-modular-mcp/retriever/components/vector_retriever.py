"""Local Qdrant retriever + writer components.

These thin wrappers preserve the legacy ``storage`` semantics (collection
auto-create, dataset_id filter, payload schema) so the existing VectorDB
directory keeps working without re-ingest.
"""
from __future__ import annotations

from typing import List

from haystack import Document, component

from .. import storage
from ..config import Config


@component
class LocalQdrantRetriever:
    """Vector retrieval against the embedded Qdrant DB.

    No-op when no embedding is provided -- the retrieval pipeline runs the
    embedder first; an empty vector means semantic search was disabled.
    """

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    @component.output_types(documents=List[Document])
    def run(
        self,
        embedding: List[float],
        dataset_ids: List[str],
        top_k: int = 200,
    ) -> dict:
        if not embedding or not dataset_ids:
            return {"documents": []}
        client = storage.open_qdrant(self.cfg)
        storage.ensure_collection(client, self.cfg)
        rows = storage.vector_search(client, self.cfg, list(embedding), dataset_ids, top_k)
        if not rows:
            return {"documents": []}
        with storage.sqlite_session(self.cfg) as conn:
            chunks = storage.fetch_chunks(conn, [r["chunk_id"] for r in rows])
        docs: list[Document] = []
        for rank, row in enumerate(rows, 1):
            chunk = chunks.get(row["chunk_id"])
            if not chunk:
                continue
            meta = {
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
                "vector_rank": rank,
                "vector_score": float(row["score"]),
            }
            docs.append(
                Document(id=row["chunk_id"], content=chunk["content"], meta=meta, score=float(row["score"]))
            )
        return {"documents": docs}


@component
class LocalQdrantWriter:
    """Write embedded documents to the local Qdrant collection."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    @component.output_types(written=int)
    def run(self, documents: List[Document], has_vector: bool = True) -> dict:
        if not has_vector or not documents:
            return {"written": 0}
        client = storage.open_qdrant(self.cfg)
        storage.ensure_collection(client, self.cfg)
        rows: list[tuple[str, list[float], dict]] = []
        for doc in documents:
            embedding = getattr(doc, "embedding", None)
            if not embedding:
                continue
            meta = doc.meta or {}
            rows.append(
                (
                    doc.id,
                    list(embedding),
                    {
                        "dataset_id": meta.get("dataset_id"),
                        "document_id": meta.get("document_id"),
                        "document_name": meta.get("document_name"),
                        "position": int(meta.get("position", 0)),
                        "parent_content": meta.get("parent_content", ""),
                        "is_hierarchical": bool(meta.get("is_hierarchical", False)),
                        "metadata": meta.get("metadata") or {},
                    },
                )
            )
        storage.upsert_vectors(client, self.cfg, rows)
        return {"written": len(rows)}
