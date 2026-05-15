"""MCP tool handlers backed by the in-process retriever package."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

from retriever import api as retriever_api
from retriever import graph as retriever_graph
from retriever import storage
from retriever.config import load_config
from retriever.hipporag import index as hipporag_index
from retriever.hipporag import query as hipporag_query
from retriever.hipporag import ppr as hipporag_ppr
from retriever.hipporag import synonyms as hipporag_synonyms
from retriever.pipelines import editor_store
from retriever.pipelines import profiles as pipeline_profiles

from . import bootstrap
from .protocol import text_result
from .runtime import silenced_stdout

# Process-wide PPR engine. ``warm()`` is lazy and re-checks the SQLite
# checksum on every call, so reloading after ingest happens automatically.
_PPR_ENGINE: hipporag_ppr.PPREngine | None = None


def _ppr_engine(cfg) -> hipporag_ppr.PPREngine:
    global _PPR_ENGINE
    if _PPR_ENGINE is None:
        _PPR_ENGINE = hipporag_ppr.PPREngine(cfg, cfg.hipporag)
    return _PPR_ENGINE

# Supported document extensions for upload_directory bulk ingest.
_SUPPORTED_EXTS = frozenset({".txt", ".md", ".pdf", ".docx", ".xlsx", ".csv"})


# ----- shared helpers -----------------------------------------------------

def _resolve_datasets(arg: Any) -> list[str]:
    if isinstance(arg, list) and arg:
        return [str(x) for x in arg if str(x).strip()]
    return list(bootstrap.DEFAULT_DATASET_IDS)


def _row_dict(row: tuple, cols: list[str]) -> dict:
    return dict(zip(cols, row))


def _require_str(args: dict, key: str) -> str | None:
    value = args.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _pipeline_name(args: dict) -> str:
    """Extract the optional ``pipeline`` arg, defaulting to ``default``."""
    value = args.get("pipeline")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "default"


def _safe_int(args: dict, key: str, default: int, *, lo: int, hi: int) -> int:
    try:
        value = int(args.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(lo, min(hi, value))


def _under_data_root(path: Path, data_root: Path) -> bool:
    try:
        path.resolve().relative_to(data_root.resolve())
        return True
    except ValueError:
        return False


def _editor_state_path(cfg) -> Path:
    return cfg.data_root / "pipeline_editor_state.json"


def _read_editor_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _probe_editor(url: str, timeout: float = 0.8) -> bool:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/health", timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    return str(pid) in result.stdout


def _kill_pid(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0


def _current_editor_status(cfg) -> dict[str, Any]:
    state_path = _editor_state_path(cfg)
    state = _read_editor_state(state_path)
    url = str(state.get("url") or "")
    pid_raw = state.get("pid")
    pid = int(pid_raw) if isinstance(pid_raw, int) or str(pid_raw).isdigit() else 0
    alive = bool(url) and _probe_editor(url)
    if alive:
        return {
            "running": True,
            "url": url,
            "pid": pid,
            "port": state.get("port"),
            "started_at": state.get("started_at"),
            "state_path": str(state_path),
            "reused": True,
        }
    if state_path.exists() and not _pid_alive(pid):
        try:
            state_path.unlink(missing_ok=True)
        except OSError:
            pass
    return {
        "running": False,
        "url": "",
        "pid": pid,
        "port": state.get("port"),
        "started_at": state.get("started_at"),
        "state_path": str(state_path),
        "reused": False,
    }


def _launch_pipeline_editor(cfg, preferred_port: int, open_browser: bool) -> dict[str, Any]:
    status = _current_editor_status(cfg)
    if status["running"]:
        if open_browser:
            webbrowser.open(status["url"])
        return status

    state_path = _editor_state_path(cfg)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        state_path.unlink(missing_ok=True)
    except OSError:
        pass

    cmd = [
        *bootstrap.PYTHON_CMD,
        str(bootstrap.ROOT_PATH / "pipeline_editor.py"),
        "--port",
        str(preferred_port),
        "--state-file",
        str(state_path),
        "--no-browser",
    ]

    creationflags = 0
    for flag_name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW"):
        creationflags |= int(getattr(subprocess, flag_name, 0))

    proc = subprocess.Popen(
        cmd,
        cwd=str(bootstrap.ROOT_PATH),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creationflags,
    )

    deadline = time.time() + 10.0
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        state = _read_editor_state(state_path)
        url = str(state.get("url") or "")
        if url and _probe_editor(url, timeout=0.5):
            pid_raw = state.get("pid")
            pid = int(pid_raw) if isinstance(pid_raw, int) or str(pid_raw).isdigit() else proc.pid
            if open_browser:
                webbrowser.open(url)
            return {
                "running": True,
                "url": url,
                "pid": pid,
                "port": state.get("port"),
                "started_at": state.get("started_at"),
                "state_path": str(state_path),
                "reused": False,
            }
        time.sleep(0.2)

    raise RuntimeError("pipeline editor failed to start within 10 seconds")


# ----- search -------------------------------------------------------------

def tool_search(args: dict) -> dict:
    query = _require_str(args, "query")
    if not query:
        return text_result("query is required and must be a non-empty string", is_error=True)
    datasets = _resolve_datasets(args.get("dataset_ids"))
    if not datasets:
        return text_result(
            "dataset_ids is empty. Pass dataset_ids or set RETRIEVER_DEFAULT_DATASETS.",
            is_error=True,
        )

    cfg = load_config()
    pipeline_name = _pipeline_name(args)
    fusion = args.get("fusion") if isinstance(args.get("fusion"), str) else None
    parent_chunk_replace = args.get("parent_chunk_replace") if isinstance(args.get("parent_chunk_replace"), bool) else None
    metadata_condition = args.get("metadata_condition") if isinstance(args.get("metadata_condition"), dict) else None

    with silenced_stdout():
        data = retriever_api.hybrid_search(
            cfg,
            query.strip(),
            datasets,
            pipeline=pipeline_name,
            top=_safe_int(args, "top_n", 12, lo=1, hi=50),
            top_k=_safe_int(args, "top_k", 200, lo=1, hi=500),
            vector_similarity_weight=float(args.get("vector_similarity_weight", 0.5)),
            keyword=bool(args.get("keyword", True)),
            fusion=fusion,
            parent_chunk_replace=parent_chunk_replace,
            metadata_condition=metadata_condition,
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
                "metadata": c.get("metadata", {}),
            },
        })
        citations.append({
            "document_name": c["document_name"],
            "position": c["position"],
            "score": c["similarity"],
            "chunk_id": c["chunk_id"],
        })
    return text_result({
        "query": query.strip(),
        "dataset_ids": datasets,
        "total": data["total"],
        "contexts": contexts,
        "citations": citations,
    })


# ----- datasets -----------------------------------------------------------

def tool_list_datasets(_args: dict) -> dict:
    cfg = load_config()
    with storage.sqlite_session(cfg) as conn:
        rows = conn.execute(
            "SELECT dataset_id, name, description, created_at FROM datasets ORDER BY created_at DESC"
        ).fetchall()
    cols = ["id", "name", "description", "created_at"]
    return text_result([_row_dict(row, cols) for row in rows])


def tool_get_dataset(args: dict) -> dict:
    ds = _require_str(args, "dataset_id")
    if not ds:
        return text_result("dataset_id is required", is_error=True)
    cfg = load_config()
    with storage.sqlite_session(cfg) as conn:
        row = conn.execute(
            "SELECT dataset_id, name, description, created_at FROM datasets WHERE dataset_id = ?",
            (ds,),
        ).fetchone()
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


# ----- documents ----------------------------------------------------------

def tool_upload_directory(args: dict) -> dict:
    ds = _require_str(args, "dataset_id")
    dp = _require_str(args, "dir_path")
    if not ds:
        return text_result("dataset_id is required", is_error=True)
    if not dp:
        return text_result("dir_path is required", is_error=True)

    dir_path = Path(dp)
    if not dir_path.is_dir():
        return text_result(f"Directory not found or not a directory: {dp}", is_error=True)

    ext = args.get("file_extension")
    if ext and not ext.startswith("."):
        ext = "." + ext

    cfg = load_config()
    pipeline_name = _pipeline_name(args)
    metadata = args.get("metadata") if isinstance(args.get("metadata"), dict) else None
    skip_embedding = bool(args.get("skip_embedding", False))
    use_hierarchical = args.get("use_hierarchical")
    auto_hipporag = bool(args.get("auto_hipporag", False))

    results: list[dict] = []
    errors: list[dict] = []

    with silenced_stdout():
        for file_path in dir_path.rglob("*"):
            if not file_path.is_file():
                continue
            suffix = file_path.suffix.lower()
            if ext and suffix != ext.lower():
                continue
            if not ext and suffix not in _SUPPORTED_EXTS:
                continue
            try:
                out = retriever_api.upload_document(
                    cfg,
                    ds,
                    str(file_path),
                    pipeline=pipeline_name,
                    skip_embedding=skip_embedding,
                    use_hierarchical=use_hierarchical,
                    metadata=metadata,
                )
                results.append({"file": str(file_path), "response": out})
            except Exception as exc:  # noqa: BLE001 — report per-file failures, keep going
                errors.append({"file": str(file_path), "error": str(exc)})

    hipporag_summary: dict | None = None
    if auto_hipporag and results:
        try:
            with silenced_stdout():
                with storage.sqlite_session(cfg) as sconn:
                    hipporag_summary = hipporag_index.index_dataset(
                        cfg, sconn, ds, rebuild_synonyms_after=True
                    )
        except Exception as exc:  # noqa: BLE001
            hipporag_summary = {"error": str(exc)}

    return text_result({
        "dataset_id": ds,
        "directory": dp,
        "processed_count": len(results),
        "error_count": len(errors),
        "results": results,
        "errors": errors,
        **({"hipporag": hipporag_summary} if hipporag_summary is not None else {}),
    })


def tool_upload_document(args: dict) -> dict:
    ds = _require_str(args, "dataset_id")
    fp = _require_str(args, "file_path")
    if not ds:
        return text_result("dataset_id is required", is_error=True)
    if not fp:
        return text_result("file_path is required", is_error=True)
    cfg = load_config()
    pipeline_name = _pipeline_name(args)
    metadata = args.get("metadata") if isinstance(args.get("metadata"), dict) else None
    auto_hipporag = bool(args.get("auto_hipporag", False))
    with silenced_stdout():
        out = retriever_api.upload_document(
            cfg,
            ds,
            fp,
            pipeline=pipeline_name,
            skip_embedding=bool(args.get("skip_embedding", False)),
            use_hierarchical=args.get("use_hierarchical"),
            metadata=metadata,
        )
    hipporag_summary: dict | None = None
    if auto_hipporag:
        doc_id = isinstance(out, dict) and out.get("document_id") or ""
        if doc_id:
            try:
                with silenced_stdout():
                    with storage.sqlite_session(cfg) as sconn:
                        hipporag_summary = hipporag_index.index_document(
                            cfg, sconn, doc_id, rebuild_synonyms_after=False
                        )
            except Exception as exc:  # noqa: BLE001 — report but don't fail the upload
                hipporag_summary = {"error": str(exc)}
    return text_result({
        "dataset_id": ds,
        "file": fp,
        "response": out,
        **({"hipporag": hipporag_summary} if hipporag_summary is not None else {}),
    })


def tool_list_documents(args: dict) -> dict:
    ds = _require_str(args, "dataset_id")
    if not ds:
        return text_result("dataset_id is required", is_error=True)
    keywords = args.get("keywords")
    offset = _safe_int(args, "offset", 0, lo=0, hi=10**9)
    limit = _safe_int(args, "limit", 30, lo=1, hi=200)
    cfg = load_config()
    sql = (
        "SELECT document_id, dataset_id, name, source_path, content_path, size_bytes, "
        "chunk_count, has_vector, metadata_json, created_at FROM documents WHERE dataset_id = ?"
    )
    params: list[Any] = [ds]
    if isinstance(keywords, str) and keywords:
        sql += " AND LOWER(name) LIKE ?"
        params.append(f"%{keywords.lower()}%")
    sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    with storage.sqlite_session(cfg) as conn:
        rows = conn.execute(sql, params).fetchall()
    cols = [
        "document_id", "dataset_id", "name", "source_path", "content_path",
        "size_bytes", "chunk_count", "has_vector", "metadata_json", "created_at",
    ]
    docs = []
    for row in rows:
        doc = _row_dict(row, cols)
        try:
            doc["metadata"] = json.loads(doc.pop("metadata_json") or "{}")
        except (TypeError, ValueError):
            doc["metadata"] = {}
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
            "SELECT document_id, dataset_id, name, source_path, content_path, size_bytes, "
            "chunk_count, has_vector, metadata_json, created_at FROM documents "
            "WHERE dataset_id = ? AND document_id = ?",
            (ds, doc),
        ).fetchone()
    if not row:
        return text_result(f"document not found: {doc}", is_error=True)
    cols = [
        "document_id", "dataset_id", "name", "source_path", "content_path",
        "size_bytes", "chunk_count", "has_vector", "metadata_json", "created_at",
    ]
    doc_obj = _row_dict(row, cols)
    try:
        doc_obj["metadata"] = json.loads(doc_obj.pop("metadata_json") or "{}")
    except (TypeError, ValueError):
        doc_obj["metadata"] = {}
    return text_result(doc_obj)


def tool_list_chunks(args: dict) -> dict:
    ds = _require_str(args, "dataset_id")
    doc = _require_str(args, "document_id")
    if not ds or not doc:
        return text_result("dataset_id and document_id are required", is_error=True)
    keywords = args.get("keywords")
    offset = _safe_int(args, "offset", 0, lo=0, hi=10**9)
    limit = _safe_int(args, "limit", 30, lo=1, hi=200)
    cfg = load_config()
    sql = (
        "SELECT chunk_id, document_id, dataset_id, position, content, parent_content, "
        "parent_id, child_id, is_hierarchical, is_contextual, metadata_json, has_vector "
        "FROM chunks WHERE dataset_id = ? AND document_id = ?"
    )
    params: list[Any] = [ds, doc]
    if isinstance(keywords, str) and keywords:
        sql += " AND LOWER(content) LIKE ?"
        params.append(f"%{keywords.lower()}%")
    sql += " ORDER BY position LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    with storage.sqlite_session(cfg) as conn:
        rows = conn.execute(sql, params).fetchall()
    cols = [
        "id", "document_id", "dataset_id", "position", "content", "parent_content",
        "parent_id", "child_id", "is_hierarchical", "is_contextual", "metadata_json", "has_vector",
    ]
    chunks = []
    for row in rows:
        chunk = _row_dict(row, cols)
        try:
            chunk["metadata"] = json.loads(chunk.pop("metadata_json") or "{}")
        except (TypeError, ValueError):
            chunk["metadata"] = {}
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
        row = conn.execute(
            "SELECT content_path FROM documents WHERE dataset_id = ? AND document_id = ?",
            (ds, doc),
        ).fetchone()
    if not row:
        return text_result(f"document not found: {doc}", is_error=True)
    path = Path(row[0])
    if not _under_data_root(path, cfg.data_root):
        return text_result(
            f"refusing to read {path}: outside data_root {cfg.data_root}", is_error=True
        )
    return text_result({
        "document_id": doc,
        "content_path": str(path),
        "content": path.read_text(encoding="utf-8", errors="replace"),
    })


def tool_delete_document(args: dict) -> dict:
    ds = _require_str(args, "dataset_id")
    doc = _require_str(args, "document_id")
    if not ds or not doc:
        return text_result("dataset_id and document_id are required", is_error=True)
    cfg = load_config()
    with storage.sqlite_session(cfg) as conn:
        # Delete chunk_fts rows by joining chunks first so we never widen the
        # delete to other documents that happen to share a chunk_id pattern.
        conn.execute(
            "DELETE FROM chunk_fts WHERE chunk_id IN (SELECT chunk_id FROM chunks WHERE document_id = ?)",
            (doc,),
        )
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (doc,))
        conn.execute("DELETE FROM documents WHERE document_id = ?", (doc,))
    shutil.rmtree(cfg.document_dir(ds, doc), ignore_errors=True)
    return text_result({"deleted": doc})


# ----- pipelines ----------------------------------------------------------

def tool_list_pipelines(_args: dict) -> dict:
    cfg = load_config()
    pipeline_profiles.sync_with_disk(cfg)
    return text_result({
        "default_ingest": {
            "chunk_chars": cfg.ingest.chunk_chars,
            "chunk_overlap": cfg.ingest.chunk_overlap,
        },
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
        "profiles": pipeline_profiles.describe(),
    })


def tool_save_pipeline(args: dict) -> dict:
    """Create a new pipeline profile and save it to ``DATA_ROOT/pipelines.json``."""
    cfg = load_config()
    result = editor_store.save_pipeline_payload(args, cfg=cfg)
    if result.get("error"):
        return text_result(result["error"], is_error=True)
    pipeline_profiles.sync_with_disk(cfg)
    return text_result(result)


def tool_open_pipeline_editor(args: dict) -> dict:
    cfg = load_config()
    preferred_port = _safe_int(args, "preferred_port", 8765, lo=1, hi=65535)
    open_browser = bool(args.get("open_browser", True))
    try:
        status = _launch_pipeline_editor(cfg, preferred_port, open_browser)
    except Exception as exc:  # noqa: BLE001
        return text_result(f"Failed to open pipeline editor: {exc}", is_error=True)
    return text_result(status)


def tool_get_pipeline_editor(_args: dict) -> dict:
    cfg = load_config()
    return text_result(_current_editor_status(cfg))


def tool_close_pipeline_editor(_args: dict) -> dict:
    cfg = load_config()
    status = _current_editor_status(cfg)
    state_path = _editor_state_path(cfg)
    if not status["running"]:
        return text_result({"running": False, "closed": False, "state_path": str(state_path)})
    pid = int(status.get("pid") or 0)
    closed = _kill_pid(pid)
    if closed:
        try:
            state_path.unlink(missing_ok=True)
        except OSError:
            pass
    return text_result({
        "running": False if closed else True,
        "closed": closed,
        "pid": pid,
        "url": status.get("url", ""),
        "state_path": str(state_path),
    })


# ----- diagnostics --------------------------------------------------------

def tool_health(_args: dict) -> dict:
    cfg = load_config()
    cfg.ensure_dirs()
    with storage.sqlite_session(cfg) as conn:
        datasets = conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0]
        documents = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    embedding_configured = bool(cfg.embedding and cfg.embedding.is_configured)
    return text_result({
        "status": "healthy",
        "backend": "self-contained",
        "data_root": str(cfg.data_root),
        "db_path": str(cfg.db_path),
        "vector_db_path": str(cfg.vector_db_path),
        "embedding_configured": embedding_configured,
        "embedding_model": cfg.embedding.model if cfg.embedding else "",
        "counts": {"datasets": datasets, "documents": documents, "chunks": chunks},
    })


# ----- graph --------------------------------------------------------------

def tool_graph_query(args: dict) -> dict:
    cypher = _require_str(args, "cypher")
    if not cypher:
        return text_result("cypher is required", is_error=True)
    params = args.get("params") or {}
    if not isinstance(params, dict):
        return text_result("params must be an object", is_error=True)
    limit = _safe_int(args, "limit", 50, lo=1, hi=500)
    cfg = load_config()
    try:
        with silenced_stdout():
            gconn = retriever_graph.open_graph(cfg)
            result = retriever_graph.run_query(gconn, cypher, params, limit=limit)
    except Exception as exc:  # noqa: BLE001 — surface Kùzu/parser errors back to the caller
        return text_result(f"graph_query failed: {exc}", is_error=True)
    return text_result(result)


def tool_graph_rebuild(_args: dict) -> dict:
    cfg = load_config()
    try:
        with silenced_stdout():
            with storage.sqlite_session(cfg) as sconn:
                gconn = retriever_graph.open_graph(cfg)
                counts = retriever_graph.rebuild_from_sqlite(gconn, sconn)
    except Exception as exc:  # noqa: BLE001
        return text_result(f"graph_rebuild failed: {exc}", is_error=True)
    return text_result({"status": "ok", **counts})


# ----- HippoRAG ----------------------------------------------------------

def tool_hipporag_index(args: dict) -> dict:
    cfg = load_config()
    ds = _require_str(args, "dataset_id")
    if not ds:
        return text_result("dataset_id is required", is_error=True)
    rebuild_syn = bool(args.get("rebuild_synonyms", True))
    max_workers = _safe_int(args, "max_workers", 4, lo=1, hi=16)
    try:
        with silenced_stdout():
            with storage.sqlite_session(cfg) as sconn:
                result = hipporag_index.index_dataset(
                    cfg, sconn, ds,
                    rebuild_synonyms_after=rebuild_syn,
                    max_workers=max_workers,
                )
        _ppr_engine(cfg).invalidate()
    except Exception as exc:  # noqa: BLE001
        return text_result(f"hipporag_index failed: {exc}", is_error=True)
    return text_result({"status": "ok", "dataset_id": ds, **result})


def tool_hipporag_index_document(args: dict) -> dict:
    cfg = load_config()
    doc_id = _require_str(args, "document_id")
    if not doc_id:
        return text_result("document_id is required", is_error=True)
    rebuild_syn = bool(args.get("rebuild_synonyms", False))
    try:
        with silenced_stdout():
            with storage.sqlite_session(cfg) as sconn:
                result = hipporag_index.index_document(
                    cfg, sconn, doc_id, rebuild_synonyms_after=rebuild_syn,
                )
        _ppr_engine(cfg).invalidate()
    except Exception as exc:  # noqa: BLE001
        return text_result(f"hipporag_index_document failed: {exc}", is_error=True)
    return text_result({"status": "ok", "document_id": doc_id, **result})


def tool_hipporag_refresh_synonyms(_args: dict) -> dict:
    cfg = load_config()
    try:
        with silenced_stdout():
            with storage.sqlite_session(cfg) as sconn:
                result = hipporag_synonyms.rebuild_synonyms(sconn, cfg.hipporag)
                retriever_graph.mark_dirty(sconn)
        _ppr_engine(cfg).invalidate()
    except Exception as exc:  # noqa: BLE001
        return text_result(f"hipporag_refresh_synonyms failed: {exc}", is_error=True)
    return text_result({"status": "ok", **result})


def tool_hipporag_search(args: dict) -> dict:
    cfg = load_config()
    q = _require_str(args, "query")
    if not q:
        return text_result("query is required", is_error=True)
    dataset_ids = _resolve_datasets(args.get("dataset_ids"))
    top = _safe_int(args, "top_n", cfg.hipporag.top_chunks, lo=1, hi=100)
    try:
        with silenced_stdout():
            with storage.sqlite_session(cfg) as sconn:
                engine = _ppr_engine(cfg)
                result = hipporag_query.search(
                    cfg, sconn, engine, q, dataset_ids, top_chunks=top,
                )
    except Exception as exc:  # noqa: BLE001
        return text_result(f"hipporag_search failed: {exc}", is_error=True)
    return text_result({
        "query": q,
        "dataset_ids": dataset_ids,
        "query_entities": result.query_entities,
        "seed_entities": result.seed_entities,
        "top_ppr_entities": [
            {"entity_id": eid, "score": round(score, 6)}
            for eid, score in result.ppr_entities_top
        ],
        "chunks": result.chunks,
    })


def tool_hipporag_stats(_args: dict) -> dict:
    cfg = load_config()
    try:
        with silenced_stdout():
            with storage.sqlite_session(cfg) as sconn:
                counts = {
                    "entities": sconn.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
                    "triples": sconn.execute("SELECT COUNT(*) FROM triples").fetchone()[0],
                    "mentions": sconn.execute("SELECT COUNT(*) FROM chunk_mentions").fetchone()[0],
                    "synonyms": sconn.execute("SELECT COUNT(*) FROM entity_synonyms").fetchone()[0],
                    "embeddings": sconn.execute("SELECT COUNT(*) FROM entity_embeddings").fetchone()[0],
                    "cached_extractions": sconn.execute("SELECT COUNT(*) FROM extraction_cache").fetchone()[0],
                }
                dirty = retriever_graph.is_dirty(sconn)
                last_index = retriever_graph.get_state(sconn, "last_index_at", "")
                last_rebuild = retriever_graph.get_state(sconn, "last_rebuilt_at", "")
                checksum = retriever_graph.graph_checksum(sconn)
                warm = _ppr_engine(cfg).warm(sconn)
    except Exception as exc:  # noqa: BLE001
        return text_result(f"hipporag_stats failed: {exc}", is_error=True)
    return text_result({
        "counts": counts,
        "graph_dirty": dirty,
        "last_index_at": last_index,
        "last_rebuilt_at": last_rebuild,
        "checksum": checksum,
        "ppr": warm,
    })


HANDLERS = {
    "search": tool_search,
    "list_datasets": tool_list_datasets,
    "get_dataset": tool_get_dataset,
    "create_dataset": tool_create_dataset,
    "delete_dataset": tool_delete_dataset,
    "upload_document": tool_upload_document,
    "upload_directory": tool_upload_directory,
    "list_documents": tool_list_documents,
    "get_document": tool_get_document,
    "list_chunks": tool_list_chunks,
    "get_document_content": tool_get_document_content,
    "delete_document": tool_delete_document,
    "list_pipelines": tool_list_pipelines,
    "save_pipeline": tool_save_pipeline,
    "open_pipeline_editor": tool_open_pipeline_editor,
    "get_pipeline_editor": tool_get_pipeline_editor,
    "close_pipeline_editor": tool_close_pipeline_editor,
    "health": tool_health,
    "graph_query": tool_graph_query,
    "graph_rebuild": tool_graph_rebuild,
    "hipporag_index": tool_hipporag_index,
    "hipporag_index_document": tool_hipporag_index_document,
    "hipporag_refresh_synonyms": tool_hipporag_refresh_synonyms,
    "hipporag_search": tool_hipporag_search,
    "hipporag_stats": tool_hipporag_stats,
}
