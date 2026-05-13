"""Tool handlers backed by local SQLite/Qdrant storage, not FastAPI."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from scripts.config import load_config
from scripts import ingest as local_ingest
from scripts import search as local_search
from scripts import storage

from . import bootstrap
from .protocol import text_result
from .runtime import silenced_stdout


def _resolve_datasets(arg: Any) -> list[str]:
    if isinstance(arg, list) and arg:
        return [str(x) for x in arg if str(x).strip()]
    return list(bootstrap.DEFAULT_DATASET_IDS)


def _row_dict(row: tuple, cols: list[str]) -> dict:
    return dict(zip(cols, row))


def _require_str(args: dict, key: str) -> str | None:
    value = args.get(key)
    return value if isinstance(value, str) and value.strip() else None


def tool_search(args: dict) -> dict:
    query = _require_str(args, "query")
    if not query:
        return text_result("query is required and must be a non-empty string", is_error=True)
    datasets = _resolve_datasets(args.get("dataset_ids"))
    if not datasets:
        return text_result("dataset_ids is empty. Pass dataset_ids or set RETRIEVER_DEFAULT_DATASETS.", is_error=True)

    cfg = load_config()
    with silenced_stdout():
        data = local_search.hybrid_search(
            cfg,
            query.strip(),
            datasets,
            top=max(1, min(50, int(args.get("top_n", 12)))),
            top_k=max(1, min(500, int(args.get("top_k", 200)))),
            vector_similarity_weight=float(args.get("vector_similarity_weight", 0.5)),
            keyword=bool(args.get("keyword", True)),
            fusion=args.get("fusion") if isinstance(args.get("fusion"), str) else None,
            parent_chunk_replace=args.get("parent_chunk_replace") if isinstance(args.get("parent_chunk_replace"), bool) else None,
            metadata_condition=args.get("metadata_condition") if isinstance(args.get("metadata_condition"), dict) else None,
        )

    contexts: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    for c in data["items"]:
        contexts.append({
            "text": c["content"],
            "source": {
                "dataset_id": c["dataset_id"],
                "document_id": c["document_id"],
                "document_name": c["document_name"],
                "position": c["position"],
                "chunk_id": c["chunk_id"],
                "similarity": c["similarity"],
                "vector_similarity": c["vector_similarity"],
                "term_similarity": c["term_similarity"],
            },
        })
        citations.append({
            "document_name": c["document_name"],
            "position": c["position"],
            "score": c["similarity"],
            "chunk_id": c["chunk_id"],
        })
    return text_result({"query": query.strip(), "dataset_ids": datasets, "total": data["total"], "contexts": contexts, "citations": citations})


def tool_list_datasets(_args: dict) -> dict:
    cfg = load_config()
    with storage.sqlite_session(cfg) as conn:
        rows = conn.execute("SELECT dataset_id, name, description, created_at FROM datasets ORDER BY created_at DESC").fetchall()
    cols = ["id", "name", "description", "created_at"]
    return text_result([_row_dict(row, cols) for row in rows])


def tool_get_dataset(args: dict) -> dict:
    ds = _require_str(args, "dataset_id")
    if not ds:
        return text_result("dataset_id is required", is_error=True)
    cfg = load_config()
    with storage.sqlite_session(cfg) as conn:
        row = conn.execute("SELECT dataset_id, name, description, created_at FROM datasets WHERE dataset_id = ?", (ds,)).fetchone()
    if not row:
        return text_result(f"dataset not found: {ds}", is_error=True)
    return text_result(_row_dict(row, ["id", "name", "description", "created_at"]))


def tool_create_dataset(args: dict) -> dict:
    name = _require_str(args, "name")
    if not name:
        return text_result("name is required", is_error=True)
    dataset_id = storage.slug(name)
    cfg = load_config()
    with storage.sqlite_session(cfg) as conn:
        storage.ensure_dataset(conn, dataset_id, name, str(args.get("description") or ""))
    cfg.dataset_dir(dataset_id).mkdir(parents=True, exist_ok=True)
    return text_result({"id": dataset_id, "name": name, "description": args.get("description") or ""})


def tool_delete_dataset(args: dict) -> dict:
    ds = _require_str(args, "dataset_id")
    if not ds:
        return text_result("dataset_id is required", is_error=True)
    cfg = load_config()
    with storage.sqlite_session(cfg) as conn:
        conn.execute("DELETE FROM chunk_fts WHERE dataset_id = ?", (ds,))
        conn.execute("DELETE FROM chunks WHERE dataset_id = ?", (ds,))
        conn.execute("DELETE FROM documents WHERE dataset_id = ?", (ds,))
        conn.execute("DELETE FROM datasets WHERE dataset_id = ?", (ds,))
    shutil.rmtree(cfg.dataset_dir(ds), ignore_errors=True)
    return text_result({"deleted": ds})


def tool_upload_document(args: dict) -> dict:
    ds = _require_str(args, "dataset_id")
    fp = _require_str(args, "file_path")
    if not ds:
        return text_result("dataset_id is required", is_error=True)
    if not fp:
        return text_result("file_path is required", is_error=True)
    cfg = load_config()
    with silenced_stdout():
        metadata = args.get("metadata") if isinstance(args.get("metadata"), dict) else None
        out = local_ingest.upload_document(
            cfg,
            ds,
            fp,
            skip_embedding=bool(args.get("skip_embedding", False)),
            use_hierarchical=args.get("use_hierarchical"),
            metadata=metadata,
        )
    return text_result({"dataset_id": ds, "file": fp, "response": out})


def tool_list_documents(args: dict) -> dict:
    ds = _require_str(args, "dataset_id")
    if not ds:
        return text_result("dataset_id is required", is_error=True)
    keywords = args.get("keywords")
    offset = int(args.get("offset", 0))
    limit = int(args.get("limit", 30))
    cfg = load_config()
    sql = "SELECT document_id, dataset_id, name, source_path, content_path, size_bytes, chunk_count, has_vector, metadata_json, created_at FROM documents WHERE dataset_id = ?"
    params: list[Any] = [ds]
    if isinstance(keywords, str) and keywords:
        sql += " AND LOWER(name) LIKE ?"
        params.append(f"%{keywords.lower()}%")
    sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    with storage.sqlite_session(cfg) as conn:
        rows = conn.execute(sql, params).fetchall()
    cols = ["document_id", "dataset_id", "name", "source_path", "content_path", "size_bytes", "chunk_count", "has_vector", "metadata_json", "created_at"]
    docs = []
    for row in rows:
        doc = _row_dict(row, cols)
        doc["metadata"] = json.loads(doc.pop("metadata_json") or "{}")
        docs.append(doc)
    return text_result(docs)


def tool_get_document(args: dict) -> dict:
    ds = _require_str(args, "dataset_id")
    doc = _require_str(args, "document_id")
    if not ds or not doc:
        return text_result("dataset_id and document_id are required", is_error=True)
    cfg = load_config()
    with storage.sqlite_session(cfg) as conn:
        row = conn.execute(
            "SELECT document_id, dataset_id, name, source_path, content_path, size_bytes, chunk_count, has_vector, metadata_json, created_at FROM documents WHERE dataset_id = ? AND document_id = ?",
            (ds, doc),
        ).fetchone()
    if not row:
        return text_result(f"document not found: {doc}", is_error=True)
    cols = ["document_id", "dataset_id", "name", "source_path", "content_path", "size_bytes", "chunk_count", "has_vector", "metadata_json", "created_at"]
    doc_obj = _row_dict(row, cols)
    doc_obj["metadata"] = json.loads(doc_obj.pop("metadata_json") or "{}")
    return text_result(doc_obj)


def tool_list_chunks(args: dict) -> dict:
    ds = _require_str(args, "dataset_id")
    doc = _require_str(args, "document_id")
    if not ds or not doc:
        return text_result("dataset_id and document_id are required", is_error=True)
    keywords = args.get("keywords")
    offset = int(args.get("offset", 0))
    limit = int(args.get("limit", 30))
    cfg = load_config()
    sql = "SELECT chunk_id, document_id, dataset_id, position, content, parent_content, parent_id, child_id, is_hierarchical, is_contextual, metadata_json, has_vector FROM chunks WHERE dataset_id = ? AND document_id = ?"
    params: list[Any] = [ds, doc]
    if isinstance(keywords, str) and keywords:
        sql += " AND LOWER(content) LIKE ?"
        params.append(f"%{keywords.lower()}%")
    sql += " ORDER BY position LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    with storage.sqlite_session(cfg) as conn:
        rows = conn.execute(sql, params).fetchall()
    cols = ["id", "document_id", "dataset_id", "position", "content", "parent_content", "parent_id", "child_id", "is_hierarchical", "is_contextual", "metadata_json", "has_vector"]
    chunks = []
    for row in rows:
        chunk = _row_dict(row, cols)
        chunk["metadata"] = json.loads(chunk.pop("metadata_json") or "{}")
        chunk["is_hierarchical"] = bool(chunk["is_hierarchical"])
        chunk["is_contextual"] = bool(chunk["is_contextual"])
        chunks.append(chunk)
    return text_result(chunks)


def tool_get_document_content(args: dict) -> dict:
    ds = _require_str(args, "dataset_id")
    doc = _require_str(args, "document_id")
    if not ds or not doc:
        return text_result("dataset_id and document_id are required", is_error=True)
    cfg = load_config()
    with storage.sqlite_session(cfg) as conn:
        row = conn.execute("SELECT content_path FROM documents WHERE dataset_id = ? AND document_id = ?", (ds, doc)).fetchone()
    if not row:
        return text_result(f"document not found: {doc}", is_error=True)
    path = Path(row[0])
    return text_result({"document_id": doc, "content_path": str(path), "content": path.read_text(encoding="utf-8", errors="replace")})


def tool_delete_document(args: dict) -> dict:
    ds = _require_str(args, "dataset_id")
    doc = _require_str(args, "document_id")
    if not ds or not doc:
        return text_result("dataset_id and document_id are required", is_error=True)
    cfg = load_config()
    with storage.sqlite_session(cfg) as conn:
        conn.execute("DELETE FROM chunk_fts WHERE document_id = ?", (doc,))
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (doc,))
        conn.execute("DELETE FROM documents WHERE document_id = ?", (doc,))
    shutil.rmtree(cfg.document_dir(ds, doc), ignore_errors=True)
    return text_result({"deleted": doc})


def tool_list_pipelines(_args: dict) -> dict:
    cfg = load_config()
    return text_result({
        "default_ingest": {"chunk_chars": cfg.ingest.chunk_chars, "chunk_overlap": cfg.ingest.chunk_overlap},
        "hierarchical_ingest": {
            "parent_chunk_chars": cfg.ingest.parent_chunk_chars,
            "parent_chunk_overlap": cfg.ingest.parent_chunk_overlap,
            "child_chunk_chars": cfg.ingest.child_chunk_chars,
            "child_chunk_overlap": cfg.ingest.child_chunk_overlap,
        },
        "default_retrieval": {
            "hybrid_alpha": cfg.search.hybrid_alpha,
            "fusion": cfg.search.fusion,
            "rrf_k": cfg.search.rrf_k,
            "parent_chunk_replace": cfg.search.parent_chunk_replace,
            "backend": "local_sqlite_qdrant",
        },
    })


def tool_health(_args: dict) -> dict:
    cfg = load_config()
    cfg.ensure_dirs()
    with storage.sqlite_session(cfg) as conn:
        datasets = conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0]
        documents = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    return text_result({
        "status": "healthy",
        "backend": "self-contained",
        "data_root": str(cfg.data_root),
        "db_path": str(cfg.db_path),
        "vector_db_path": str(cfg.vector_db_path),
        "embedding_configured": bool(cfg.embedding.api_url and cfg.embedding.dim > 0),
        "counts": {"datasets": datasets, "documents": documents, "chunks": chunks},
    })


HANDLERS = {
    "search": tool_search,
    "list_datasets": tool_list_datasets,
    "get_dataset": tool_get_dataset,
    "create_dataset": tool_create_dataset,
    "delete_dataset": tool_delete_dataset,
    "upload_document": tool_upload_document,
    "list_documents": tool_list_documents,
    "get_document": tool_get_document,
    "list_chunks": tool_list_chunks,
    "get_document_content": tool_get_document_content,
    "delete_document": tool_delete_document,
    "list_pipelines": tool_list_pipelines,
    "health": tool_health,
}
