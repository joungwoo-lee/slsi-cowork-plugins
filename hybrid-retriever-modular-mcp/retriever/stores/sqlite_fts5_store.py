"""Haystack DocumentStore backed by SQLite FTS5 with Korean morpheme tokenization.

This store wraps the canonical `retriever.storage` primitives so existing on-disk
state (`metadata.db`) remains the source of truth. The DocumentStore protocol
methods (`count_documents`, `filter_documents`, `write_documents`,
`delete_documents`) make the store usable inside Haystack pipelines, while the
companion `Fts5Retriever` component runs FTS5 BM25 queries through kiwipiepy
preprocessing.

Document <-> chunk mapping
--------------------------
- ``Document.id`` MUST be ``f"{document_id}:{position}"`` (the canonical
  chunk_id). The indexing pipeline assigns this explicitly so existing
  consumers (search response, list_chunks, citations) see unchanged values.
- ``Document.content`` -> ``chunks.content``
- ``Document.meta`` keys consumed:
    dataset_id, document_id, document_name, position,
    parent_content, parent_id, child_id,
    is_hierarchical, is_contextual, has_vector, metadata (free-form),
    original_child_content, source_path, content_path, size_bytes
"""
from __future__ import annotations

from typing import Any, Iterable

from haystack import Document
from haystack.document_stores.types import DocumentStore, DuplicatePolicy

from .. import graph, storage
from ..config import Config


class SqliteFts5DocumentStore:
    """DocumentStore over the canonical SQLite FTS5 index.

    The store is stateless w.r.t. connections — every public method opens a
    short SQLite session via ``storage.sqlite_session(cfg)``. This keeps the
    store safe to share across pipelines and threads without explicit locking
    (SQLite serializes writers internally).
    """

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg

    # ---- Haystack DocumentStore protocol ----------------------------------

    def count_documents(self) -> int:
        with storage.sqlite_session(self._cfg) as conn:
            row = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
        return int(row[0] if row else 0)

    def filter_documents(self, filters: dict[str, Any] | None = None) -> list[Document]:
        clauses: list[str] = []
        params: list[Any] = []
        for key in ("dataset_id", "document_id"):
            if filters and key in filters:
                clauses.append(f"c.{key} = ?")
                params.append(filters[key])
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            "SELECT c.chunk_id, c.document_id, c.dataset_id, d.name, c.position, c.content, "
            "c.original_content, c.parent_content, c.parent_id, c.child_id, "
            "c.is_hierarchical, c.is_contextual, c.metadata_json, c.has_vector "
            "FROM chunks c JOIN documents d ON d.document_id = c.document_id "
            f"{where} ORDER BY c.document_id, c.position"
        )
        with storage.sqlite_session(self._cfg) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_document(row) for row in rows]

    def write_documents(
        self,
        documents: list[Document],
        policy: DuplicatePolicy = DuplicatePolicy.OVERWRITE,
    ) -> int:
        """Persist documents grouped by their source ``document_id``.

        Each group is upserted atomically: existing chunks for the document are
        replaced (matching the legacy ``upsert_document`` semantics) so callers
        don't need to issue an explicit delete first.
        """
        if not documents:
            return 0
        groups: dict[tuple[str, str], list[Document]] = {}
        for doc in documents:
            key = (str(doc.meta.get("dataset_id")), str(doc.meta.get("document_id")))
            groups.setdefault(key, []).append(doc)

        written = 0
        with storage.sqlite_session(self._cfg) as conn:
            for (dataset_id, document_id), docs in groups.items():
                if not dataset_id or not document_id:
                    raise ValueError(
                        "Document.meta must include dataset_id and document_id "
                        "for SqliteFts5DocumentStore.write_documents"
                    )
                docs.sort(key=lambda d: int(d.meta.get("position", 0)))
                head = docs[0].meta
                storage.ensure_dataset(conn, dataset_id)
                storage.upsert_document(
                    conn,
                    dataset_id=dataset_id,
                    document_id=document_id,
                    name=str(head.get("document_name") or ""),
                    source_path=str(head.get("source_path") or ""),
                    content_path=str(head.get("content_path") or ""),
                    size_bytes=int(head.get("size_bytes") or 0),
                    chunks=[_document_to_chunk_record(d) for d in docs],
                    has_vector=bool(head.get("has_vector", False)),
                    metadata=head.get("document_metadata") or None,
                )
                written += len(docs)
        return written

    def delete_documents(self, document_ids: list[str]) -> None:
        if not document_ids:
            return
        placeholders = ",".join("?" * len(document_ids))
        with storage.sqlite_session(self._cfg) as conn:
            graph.mark_dirty(conn)
            conn.execute(f"DELETE FROM chunk_fts WHERE chunk_id IN ({placeholders})", document_ids)
            conn.execute(f"DELETE FROM chunks WHERE chunk_id IN ({placeholders})", document_ids)


def _row_to_document(row: Iterable[Any]) -> Document:
    import json

    (
        chunk_id, document_id, dataset_id, name, position, content,
        original_content, parent_content, parent_id, child_id,
        is_hierarchical, is_contextual, metadata_json, has_vector,
    ) = tuple(row)
    try:
        meta_blob = json.loads(metadata_json or "{}")
    except Exception:
        meta_blob = {}
    meta = {
        "dataset_id": dataset_id,
        "document_id": document_id,
        "document_name": name,
        "position": int(position),
        "original_child_content": original_content or "",
        "parent_content": parent_content or content,
        "parent_id": int(parent_id or 0),
        "child_id": int(child_id or position),
        "is_hierarchical": bool(is_hierarchical),
        "is_contextual": bool(is_contextual),
        "has_vector": bool(has_vector),
        "metadata": meta_blob,
    }
    return Document(id=chunk_id, content=content or "", meta=meta)


def _document_to_chunk_record(doc: Document) -> dict[str, Any]:
    meta = doc.meta or {}
    content = doc.content or ""
    return {
        "child_content": content,
        "original_child_content": meta.get("original_child_content", content),
        "parent_content": meta.get("parent_content", content),
        "parent_id": int(meta.get("parent_id", 0)),
        "child_id": int(meta.get("child_id", meta.get("position", 0))),
        "global_position": int(meta.get("position", 0)),
        "is_hierarchical": bool(meta.get("is_hierarchical", False)),
        "is_contextual": bool(meta.get("is_contextual", False)),
        "metadata": meta.get("metadata") or {},
    }


__all__ = ["SqliteFts5DocumentStore", "DocumentStore"]
