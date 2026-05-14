"""Local Qdrant retriever + writer components.

Thin wrappers around the :mod:`retriever.storage` Qdrant helpers. The
embedding side is decoupled so these components stay self-contained even
when the embedding API is unconfigured -- the retrieval pipeline will simply
hand them an empty vector and they no-op.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

from haystack import Document, component

from .. import storage
from ..config import Config


def _make_cfg(data_root: str, collection: str) -> Config:
    cfg = Config(data_root=Path(data_root))
    cfg.qdrant.collection = collection
    return cfg


def _chunk_to_meta(chunk: dict, rank: int, score: float) -> dict:
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
        "vector_rank": rank,
        "vector_score": score,
    }


@component
class LocalQdrantRetriever:
    """Vector retrieval against the embedded Qdrant DB."""

    def __init__(self, data_root: str = "", collection: str = "retriever_chunks") -> None:
        self.data_root = data_root
        self.collection = collection

    @component.output_types(documents=List[Document])
    def run(
        self,
        embedding: List[float],
        dataset_ids: List[str],
        top_k: int = 200,
    ) -> dict:
        if not embedding or not dataset_ids or not self.data_root:
            return {"documents": []}

        cfg = _make_cfg(self.data_root, self.collection)
        client = storage.open_qdrant(cfg)
        storage.ensure_collection(client, cfg)
        rows = storage.vector_search(client, cfg, list(embedding), dataset_ids, top_k)
        if not rows:
            return {"documents": []}
        with storage.sqlite_session(cfg) as conn:
            chunks = storage.fetch_chunks(conn, [r["chunk_id"] for r in rows])
        docs: list[Document] = []
        for rank, row in enumerate(rows, 1):
            chunk = chunks.get(row["chunk_id"])
            if not chunk:
                continue
            meta = _chunk_to_meta(chunk, rank, float(row["score"]))
            docs.append(
                Document(id=row["chunk_id"], content=chunk["content"], meta=meta, score=float(row["score"]))
            )
        return {"documents": docs}


@component
class LocalQdrantWriter:
    """Write embedded documents to the local Qdrant collection."""

    def __init__(self, data_root: str = "", collection: str = "retriever_chunks") -> None:
        self.data_root = data_root
        self.collection = collection

    @component.output_types(written=int)
    def run(self, documents: List[Document], has_vector: bool = True) -> dict:
        if not has_vector or not documents or not self.data_root:
            return {"written": 0}

        cfg = _make_cfg(self.data_root, self.collection)
        client = storage.open_qdrant(cfg)
        cfg_embedding_dim = self._dim_from_docs(documents)
        if cfg_embedding_dim is None:
            return {"written": 0}
        # ensure_collection needs cfg.embedding.dim; fabricate a minimal cfg for it.
        from ..config import EmbeddingConfig
        cfg.embedding = EmbeddingConfig(api_url="placeholder", api_key="", model="", dim=cfg_embedding_dim)
        storage.ensure_collection(client, cfg)

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
        storage.upsert_vectors(client, cfg, rows)
        return {"written": len(rows)}

    @staticmethod
    def _dim_from_docs(documents: List[Document]) -> int | None:
        for doc in documents:
            emb = getattr(doc, "embedding", None)
            if emb:
                return len(emb)
        return None
