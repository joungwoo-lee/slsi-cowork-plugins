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
from retriever.hippo2 import index as hippo2_index
from retriever.hippo2 import ppr as hippo2_ppr
from retriever.hippo2 import synonyms as hippo2_synonyms
from retriever.pipelines import editor_store
from retriever.pipelines import get_answer_template as _pipeline_answer_template
from retriever.pipelines import profiles as pipeline_profiles

from . import bootstrap
from . import catalog
from . import job_manager
from .protocol import text_result, write_message
from .runtime import log, silenced_stdout

def _reveal_and_notify(*names: str) -> None:
    """Reveal follow-up tools and tell the client to re-fetch tools/list.

    Safe to call multiple times; reveal() is idempotent and only emits the
    list_changed notification when the visible catalog actually grew.
    """
    if catalog.reveal(*names):
        try:
            write_message({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
        except Exception as exc:  # noqa: BLE001
            log(f"failed to send tools/list_changed: {exc}")


def _reveal_admin_and_notify() -> None:
    if catalog.reveal_admin():
        try:
            write_message({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
        except Exception as exc:  # noqa: BLE001
            log(f"failed to send tools/list_changed: {exc}")

# Process-wide PPR engine. ``warm()`` is lazy and re-checks the SQLite
# checksum on every call, so reloading after ingest happens automatically.
_PPR_ENGINE: hippo2_ppr.PPREngine | None = None


def _ppr_engine(cfg) -> hippo2_ppr.PPREngine:
    global _PPR_ENGINE
    if _PPR_ENGINE is None:
        _PPR_ENGINE = hippo2_ppr.PPREngine(cfg, cfg.hippo2)
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


def _job_progress(cfg, job_id: str, progress: int, message: str) -> None:
    job_manager.update_job(cfg, job_id, progress=progress, message=message)


def _mark_dataset_ingest_profile(
    cfg,
    dataset_id: str,
    *,
    pipeline_name: str,
    content_kind: str,
    has_vectors: bool,
    hippo2_ready: bool | None = None,
) -> None:
    with storage.sqlite_session(cfg) as conn:
        current = storage.get_dataset_metadata(conn, dataset_id)
        supported = set(current.get("supported_search_pipelines") or ["default"])
        supported.add("default")
        if pipeline_name == "email":
            supported.add("email")
        if hippo2_ready or current.get("has_hippo2"):
            supported.add("hippo2")
        metadata = {
            **current,
            "first_ingest_pipeline": current.get("first_ingest_pipeline") or pipeline_name,
            "last_ingest_pipeline": pipeline_name,
            "content_kind": content_kind,
            "has_vectors": bool(has_vectors or current.get("has_vectors")),
            "has_hippo2": bool(current.get("has_hippo2") if hippo2_ready is None else hippo2_ready),
            "supported_search_pipelines": sorted(supported),
            "preferred_search_pipeline": (
                "hippo2"
                if (pipeline_name == "hippo2" and (hippo2_ready or current.get("has_hippo2")))
                else "hippo2"
                if (hippo2_ready or current.get("has_hippo2"))
                else ("email" if pipeline_name == "email" else "default")
            ),
        }
        storage.update_dataset_metadata(conn, dataset_id, metadata)


def _dataset_search_pipeline(cfg, dataset_ids: list[str], requested: str | None) -> str:
    if requested and requested.strip():
        return requested.strip()
    if not dataset_ids:
        return "default"
    with storage.sqlite_session(cfg) as conn:
        preferred: set[str] = set()
        for dataset_id in dataset_ids:
            meta = storage.get_dataset_metadata(conn, dataset_id)
            preferred.add(str(meta.get("preferred_search_pipeline") or "default"))
    return preferred.pop() if len(preferred) == 1 else "default"


def _answer_instructions_for(pipeline_name: str) -> str:
    """Look up the per-pipeline answer template from the topology JSON.

    ``pipeline_profiles.get`` falls back to the default profile for unknown
    names, so the agent always receives some template.
    """
    try:
        profile = pipeline_profiles.get(pipeline_name)
    except Exception:  # noqa: BLE001
        profile = None
    return _pipeline_answer_template(profile)


def _upload_args_from_unified(args: dict) -> dict:
    ds = _require_str(args, "dataset_id")
    path_str = _require_str(args, "path")
    if not ds:
        raise ValueError("dataset_id is required")
    if not path_str:
        raise ValueError("path is required")
    path = Path(path_str)
    if path.is_file():
        pipeline_name = _pipeline_name(args)
        return {
            "dataset_id": ds,
            "file_path": str(path),
            "use_hierarchical": args.get("use_hierarchical"),
            "skip_embedding": bool(args.get("skip_embedding", False)),
            "metadata": args.get("metadata") if isinstance(args.get("metadata"), dict) else None,
            "pipeline": pipeline_name,
        }
    if path.is_dir():
        pipeline_name = _pipeline_name(args)
        # Email-MCP converted directories (mail_*/meta.json + body.md) are
        # one email per directory, not a bulk folder. Route them through the
        # single-document path so email_loader sees the directory it expects.
        if pipeline_name == "email" and (path / "meta.json").exists():
            return {
                "dataset_id": ds,
                "file_path": str(path),
                "use_hierarchical": args.get("use_hierarchical"),
                "skip_embedding": bool(args.get("skip_embedding", False)),
                "metadata": args.get("metadata") if isinstance(args.get("metadata"), dict) else None,
                "pipeline": pipeline_name,
            }
        payload = {
            "dataset_id": ds,
            "dir_path": str(path),
            "use_hierarchical": args.get("use_hierarchical"),
            "skip_embedding": bool(args.get("skip_embedding", False)),
            "metadata": args.get("metadata") if isinstance(args.get("metadata"), dict) else None,
            "pipeline": pipeline_name,
        }
        if isinstance(args.get("file_extension"), str) and args.get("file_extension"):
            payload["file_extension"] = args.get("file_extension")
        return payload
    raise ValueError(f"Path not found or unsupported: {path}")


def _run_upload_document(cfg, args: dict, *, job_id: str | None = None) -> dict:
    ds = _require_str(args, "dataset_id")
    fp = _require_str(args, "file_path")
    if not ds:
        raise ValueError("dataset_id is required")
    if not fp:
        raise ValueError("file_path is required")
    pipeline_name = _pipeline_name(args)
    metadata = args.get("metadata") if isinstance(args.get("metadata"), dict) else None
    if job_id:
        _job_progress(cfg, job_id, 5, "indexing document")
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
    _mark_dataset_ingest_profile(
        cfg,
        ds,
        pipeline_name=pipeline_name,
        content_kind="email" if pipeline_name == "email" else "document",
        has_vectors=bool(isinstance(out, dict) and out.get("has_vector")),
        hippo2_ready=(pipeline_name == "hippo2"),
    )
    if job_id:
        _job_progress(cfg, job_id, 95, "finalizing")
    return {
        "dataset_id": ds,
        "file": fp,
        "response": out,
    }


def _run_upload_directory(cfg, args: dict, *, job_id: str | None = None) -> dict:
    ds = _require_str(args, "dataset_id")
    dp = _require_str(args, "dir_path")
    if not ds:
        raise ValueError("dataset_id is required")
    if not dp:
        raise ValueError("dir_path is required")
    dir_path = Path(dp)
    if not dir_path.is_dir():
        raise ValueError(f"Directory not found or not a directory: {dp}")
    ext = args.get("file_extension")
    if ext and not ext.startswith("."):
        ext = "." + ext
    pipeline_name = _pipeline_name(args)
    metadata = args.get("metadata") if isinstance(args.get("metadata"), dict) else None
    skip_embedding = bool(args.get("skip_embedding", False))
    use_hierarchical = args.get("use_hierarchical")

    paths: list[Path] = []
    for file_path in dir_path.rglob("*"):
        if not file_path.is_file():
            continue
        suffix = file_path.suffix.lower()
        if ext and suffix != ext.lower():
            continue
        if not ext and suffix not in _SUPPORTED_EXTS:
            continue
        paths.append(file_path)

    results: list[dict] = []
    errors: list[dict] = []
    total = max(1, len(paths))
    with silenced_stdout():
        for idx, file_path in enumerate(paths, 1):
            if job_id:
                pct = int(5 + (idx - 1) * 75 / total)
                _job_progress(cfg, job_id, pct, f"indexing {idx}/{total}: {file_path.name}")
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
            except Exception as exc:  # noqa: BLE001
                errors.append({"file": str(file_path), "error": str(exc)})

    _mark_dataset_ingest_profile(
        cfg,
        ds,
        pipeline_name=pipeline_name,
        content_kind="email" if pipeline_name == "email" else "document",
        has_vectors=any(bool((item.get("response") or {}).get("has_vector")) for item in results),
        hippo2_ready=(pipeline_name == "hippo2" and bool(results)),
    )
    if job_id:
        _job_progress(cfg, job_id, 95, "finalizing")
    return {
        "dataset_id": ds,
        "directory": dp,
        "processed_count": len(results),
        "error_count": len(errors),
        "results": results,
        "errors": errors,
    }


def _run_graph_rebuild(cfg) -> dict:
    with silenced_stdout():
        with storage.sqlite_session(cfg) as sconn:
            gconn = retriever_graph.open_graph(cfg)
            counts = retriever_graph.rebuild_from_sqlite(gconn, sconn)
    return {"status": "ok", **counts}


def _run_hippo2_index(cfg, args: dict, *, document: bool) -> dict:
    rebuild_syn = bool(args.get("rebuild_synonyms", not document))
    max_workers = _safe_int(args, "max_workers", 4, lo=1, hi=16)
    with silenced_stdout():
        with storage.sqlite_session(cfg) as sconn:
            if document:
                doc_id = _require_str(args, "document_id")
                if not doc_id:
                    raise ValueError("document_id is required")
                row = sconn.execute(
                    "SELECT dataset_id FROM documents WHERE document_id = ?",
                    (doc_id,),
                ).fetchone()
                result = hippo2_index.index_document(
                    cfg, sconn, doc_id, rebuild_synonyms_after=rebuild_syn, max_workers=max_workers,
                )
                payload = {"status": "ok", "document_id": doc_id, **result}
                if row and row[0]:
                    _mark_dataset_ingest_profile(
                        cfg,
                        row[0],
                        pipeline_name="default",
                        content_kind="document",
                        has_vectors=True,
                        hippo2_ready=True,
                    )
            else:
                ds = _require_str(args, "dataset_id")
                if not ds:
                    raise ValueError("dataset_id is required")
                result = hippo2_index.index_dataset(
                    cfg, sconn, ds, rebuild_synonyms_after=rebuild_syn, max_workers=max_workers,
                )
                payload = {"status": "ok", "dataset_id": ds, **result}
                _mark_dataset_ingest_profile(
                    cfg,
                    ds,
                    pipeline_name="default",
                    content_kind="document",
                    has_vectors=True,
                    hippo2_ready=True,
                )
    _ppr_engine(cfg).invalidate()
    return payload


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


def tool_pipeline_tutorial(_args: dict) -> dict:
    tutorial = (
        "## How to Create a New RAG Pipeline\n\n"
        "1. **Implement Components (Optional)**: If you need new logic, create a Python file in `retriever/components/`. "
        "Decorate your class with `@component` and define a `run` method.\n\n"
        "2. **Define Topology**: Create a JSON file in `retriever/pipelines/` (e.g., `my_pipeline_unified.json`). "
        "Use the node-centric schema to define components and their connections.\n\n"
        "3. **Register Profile**: Add a new entry to `retriever/pipelines/registry.json`. "
        "Specify your topology file and any runtime overrides.\n\n"
        "4. **Update Engine (Rare)**: If your component needs new input types from the search/upload API, "
        "update `retriever/pipelines/engine.py` to forward those inputs.\n\n"
        "5. **Test**: Run the MCP server and verify your new pipeline appears in `list_pipelines`."
    )
    return text_result(tutorial)


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
    requested_pipeline = args.get("pipeline") if isinstance(args.get("pipeline"), str) else None
    pipeline_name = _dataset_search_pipeline(cfg, datasets, requested_pipeline)
    fusion = args.get("fusion") if isinstance(args.get("fusion"), str) else None
    parent_chunk_replace = args.get("parent_chunk_replace") if isinstance(args.get("parent_chunk_replace"), bool) else None
    metadata_condition = args.get("metadata_condition") if isinstance(args.get("metadata_condition"), dict) else None
    # similarity_threshold acts as a server-side score floor applied before
    # top_n slicing. Clamped to [0,1] so a bogus value can't silently drop
    # every result.
    raw_threshold = args.get("similarity_threshold")
    try:
        similarity_threshold = float(raw_threshold) if raw_threshold is not None else 0.0
    except (TypeError, ValueError):
        similarity_threshold = 0.0
    similarity_threshold = max(0.0, min(1.0, similarity_threshold))

    with silenced_stdout():
        data = retriever_api.hybrid_search(
            cfg,
            query.strip(),
            datasets,
            pipeline=pipeline_name,
            top=_safe_int(args, "top_n", 12, lo=1, hi=50),
            top_k=_safe_int(args, "top_k", 200, lo=1, hi=500),
            vector_similarity_weight=float(args["vector_similarity_weight"]) if args.get("vector_similarity_weight") is not None else None,
            keyword=bool(args["keyword"]) if args.get("keyword") is not None else None,
            fusion=fusion,
            parent_chunk_replace=parent_chunk_replace,
            metadata_condition=metadata_condition,
            similarity_threshold=similarity_threshold,
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
                "graph_similarity": c.get("graph_similarity", 0.0),
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
    # search returns reranked chunks + citations — those *are* the answer,
    # so it intentionally has no flow follow-up to reveal.
    return text_result({
        "query": query.strip(),
        "dataset_ids": datasets,
        "search_pipeline": pipeline_name,
        "total": data["total"],
        "contexts": contexts,
        "citations": citations,
        "answer_instructions": _answer_instructions_for(pipeline_name),
    })


# ----- datasets -----------------------------------------------------------

def tool_list_datasets(_args: dict) -> dict:
    cfg = load_config()
    with storage.sqlite_session(cfg) as conn:
        rows = conn.execute(
            "SELECT dataset_id, name, description, metadata_json, created_at FROM datasets ORDER BY created_at DESC"
        ).fetchall()
    items = []
    for row in rows:
        obj = _row_dict(row, ["id", "name", "description", "metadata_json", "created_at"])
        try:
            obj["metadata"] = json.loads(obj.pop("metadata_json") or "{}")
        except (TypeError, ValueError):
            obj["metadata"] = {}
        items.append(obj)
    _reveal_and_notify("list_documents")
    example_ds = items[0]["id"] if items else ""
    return text_result({
        "datasets": items,
        "next_actions": {
            "browse_documents": {
                "tool": "list_documents",
                "arguments": {"dataset_id": example_ds},
                "use_when": "Browse the documents inside a dataset.",
            },
        },
    })


def tool_get_dataset(args: dict) -> dict:
    ds = _require_str(args, "dataset_id")
    if not ds:
        return text_result("dataset_id is required", is_error=True)
    cfg = load_config()
    with storage.sqlite_session(cfg) as conn:
        row = conn.execute(
            "SELECT dataset_id, name, description, metadata_json, created_at FROM datasets WHERE dataset_id = ?",
            (ds,),
        ).fetchone()
    if not row:
        return text_result(f"dataset not found: {ds}", is_error=True)
    obj = _row_dict(row, ["id", "name", "description", "metadata_json", "created_at"])
    try:
        obj["metadata"] = json.loads(obj.pop("metadata_json") or "{}")
    except (TypeError, ValueError):
        obj["metadata"] = {}
    return text_result(obj)


def tool_create_dataset(args: dict) -> dict:
    name = _require_str(args, "name")
    if not name:
        return text_result("name is required", is_error=True)
    dataset_id = storage.slug(name)
    use_when = _require_str(args, "use_when") or ""
    cfg = load_config()
    with storage.sqlite_session(cfg) as conn:
        storage.ensure_dataset(conn, dataset_id, name, str(args.get("description") or ""))
        if use_when:
            storage.merge_dataset_metadata(conn, dataset_id, {"use_when": use_when})
    cfg.dataset_dir(dataset_id).mkdir(parents=True, exist_ok=True)
    return text_result({
        "id": dataset_id,
        "name": name,
        "description": args.get("description") or "",
        "metadata": ({"use_when": use_when} if use_when else {}),
    })


def tool_delete_dataset(args: dict) -> dict:
    ds = _require_str(args, "dataset_id")
    if not ds:
        return text_result("dataset_id is required", is_error=True)
    cfg = load_config()
    with storage.sqlite_session(cfg) as conn:
        retriever_graph.mark_dirty(conn)
        conn.execute("DELETE FROM chunk_fts WHERE dataset_id = ?", (ds,))
        conn.execute("DELETE FROM chunks WHERE dataset_id = ?", (ds,))
        conn.execute("DELETE FROM documents WHERE dataset_id = ?", (ds,))
        conn.execute("DELETE FROM datasets WHERE dataset_id = ?", (ds,))
    shutil.rmtree(cfg.dataset_dir(ds), ignore_errors=True)
    return text_result({"deleted": ds})


# ----- documents ----------------------------------------------------------

def tool_upload_directory(args: dict) -> dict:
    cfg = load_config()
    try:
        return text_result(_run_upload_directory(cfg, args))
    except Exception as exc:  # noqa: BLE001
        return text_result(str(exc), is_error=True)


def tool_upload_document(args: dict) -> dict:
    cfg = load_config()
    try:
        return text_result(_run_upload_document(cfg, args))
    except Exception as exc:  # noqa: BLE001
        return text_result(str(exc), is_error=True)


def tool_upload(args: dict) -> dict:
    cfg = load_config()
    try:
        normalized = _upload_args_from_unified(args)
        run_async = bool(args.get("async", True))
        if "file_path" in normalized:
            if run_async:
                return text_result(
                    job_manager.start_job(
                        cfg,
                        job_type="upload_document",
                        args=args,
                        dataset_id=normalized["dataset_id"],
                        runner=lambda job_id: _run_upload_document(cfg, normalized, job_id=job_id),
                    )
                )
            return text_result(_run_upload_document(cfg, normalized))
        if run_async:
            return text_result(
                job_manager.start_job(
                    cfg,
                    job_type="upload_directory",
                    args=args,
                    dataset_id=normalized["dataset_id"],
                    runner=lambda job_id: _run_upload_directory(cfg, normalized, job_id=job_id),
                )
            )
        return text_result(_run_upload_directory(cfg, normalized))
    except Exception as exc:  # noqa: BLE001
        return text_result(str(exc), is_error=True)


def tool_start_upload_document(args: dict) -> dict:
    cfg = load_config()
    ds = _require_str(args, "dataset_id") or ""
    job = job_manager.start_job(
        cfg,
        job_type="upload_document",
        args=args,
        dataset_id=ds,
        runner=lambda job_id: _run_upload_document(cfg, args, job_id=job_id),
    )
    return text_result(job)


def tool_start_upload_directory(args: dict) -> dict:
    cfg = load_config()
    ds = _require_str(args, "dataset_id") or ""
    job = job_manager.start_job(
        cfg,
        job_type="upload_directory",
        args=args,
        dataset_id=ds,
        runner=lambda job_id: _run_upload_directory(cfg, args, job_id=job_id),
    )
    return text_result(job)


def tool_get_job(args: dict) -> dict:
    job_id = _require_str(args, "job_id")
    if not job_id:
        return text_result("job_id is required", is_error=True)
    cfg = load_config()
    job = job_manager.get_job(cfg, job_id)
    if not job:
        return text_result(f"job not found: {job_id}", is_error=True)
    return text_result(job)


def tool_list_jobs(args: dict) -> dict:
    cfg = load_config()
    status = _require_str(args, "status") or ""
    limit = _safe_int(args, "limit", 20, lo=1, hi=200)
    offset = _safe_int(args, "offset", 0, lo=0, hi=10**9)
    return text_result(job_manager.list_jobs(cfg, limit=limit, offset=offset, status=status))


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
        retriever_graph.mark_dirty(conn)
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


def tool_admin_help(_args: dict) -> dict:
    _reveal_admin_and_notify()
    return text_result({
        "admin_tools": [
            {
                "name": "create_dataset",
                "use_when": "Pre-create a dataset or record its use_when note before the first ingest.",
            },
            {
                "name": "delete_dataset",
                "use_when": "Permanently remove a dataset and all of its files/chunks/vectors.",
            },
            {
                "name": "get_document",
                "use_when": "Inspect one document's metadata in detail.",
            },
            {
                "name": "list_chunks",
                "use_when": "Inspect how a document was chunked after ingest.",
            },
            {
                "name": "delete_document",
                "use_when": "Permanently remove one document from a dataset.",
            },
            {
                "name": "get_dataset",
                "use_when": "Re-fetch one dataset's metadata by id (rare — list_datasets already returns full metadata).",
            },
            {
                "name": "get_document_content",
                "use_when": "Read the original full source text of a document. Rare after search — chunks already carry the relevant passages.",
            },
            {
                "name": "health",
                "use_when": "Diagnose data paths, embedding configuration, and index counts.",
            },
            {
                "name": "graph_query",
                "use_when": "Run advanced relationship queries directly against the embedded graph.",
            },
            {
                "name": "graph_rebuild",
                "use_when": "The embedded graph is missing or badly stale and automatic sync is not enough.",
            },
            {
                "name": "start_hippo2_index",
                "use_when": "Start a long-running dataset Hippo2 indexing job without blocking the MCP request.",
            },
            {
                "name": "hippo2_index",
                "use_when": "A dataset needs entity/triple extraction or full Hippo2 refresh after bulk ingest.",
            },
            {
                "name": "hippo2_index_document",
                "use_when": "Re-index one document's Hippo2 state only.",
            },
            {
                "name": "hippo2_refresh_synonyms",
                "use_when": "Rebuild synonym edges after a batch of Hippo2 indexing jobs.",
            },
            {
                "name": "hippo2_search",
                "use_when": "Directly test Hippo2 retrieval without normal search auto-routing.",
            },
            {
                "name": "hippo2_stats",
                "use_when": "Inspect Hippo2 entity/triple/synonym counts and PPR cache warmth.",
            },
            {
                "name": "list_pipelines",
                "use_when": "Inspect available ingest pipeline profiles and their settings.",
            },
            {
                "name": "save_pipeline",
                "use_when": "Create or update a reusable pipeline profile.",
            },
            {
                "name": "open_pipeline_editor",
                "use_when": "Open the visual pipeline editor for advanced pipeline editing.",
            },
            {
                "name": "get_pipeline_editor",
                "use_when": "Check whether the pipeline editor is already running.",
            },
            {
                "name": "close_pipeline_editor",
                "use_when": "Stop the pipeline editor process.",
            },
            {
                "name": "start_benchmark_pipelines",
                "use_when": "Start a long-running benchmark job asynchronously without blocking.",
            },
            {
                "name": "benchmark_pipelines",
                "use_when": (
                    "Run an end-to-end accuracy and speed benchmark across all (or selected) "
                    "pipelines. Ingests built-in test docs, runs 5 predefined queries per pipeline, "
                    "measures hit rate and avg latency, and returns a markdown report table."
                ),
            },
        ],
        "note": (
            "These tools are hidden from the default tools/list. Calling admin_help "
            "reveals them via a tools/list_changed notification, so the next "
            "tools/list will include them and they become directly callable."
        ),
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
            with storage.sqlite_session(cfg) as sconn:
                gconn = retriever_graph.open_graph(cfg)
                retriever_graph.sync_graph(gconn, sconn)
                result = retriever_graph.run_query(gconn, cypher, params, limit=limit)
    except Exception as exc:  # noqa: BLE001 — surface Kùzu/parser errors back to the caller
        return text_result(f"graph_query failed: {exc}", is_error=True)
    return text_result(result)


def tool_graph_rebuild(_args: dict) -> dict:
    cfg = load_config()
    try:
        return text_result(_run_graph_rebuild(cfg))
    except Exception as exc:  # noqa: BLE001
        return text_result(f"graph_rebuild failed: {exc}", is_error=True)


def tool_start_graph_rebuild(_args: dict) -> dict:
    cfg = load_config()
    return text_result(
        job_manager.start_job(
            cfg,
            job_type="graph_rebuild",
            args={},
            runner=lambda _job_id: _run_graph_rebuild(cfg),
        )
    )


# ----- Hippo2 ----------------------------------------------------------

def tool_hippo2_index(args: dict) -> dict:
    cfg = load_config()
    try:
        return text_result(_run_hippo2_index(cfg, args, document=False))
    except Exception as exc:  # noqa: BLE001
        return text_result(f"hippo2_index failed: {exc}", is_error=True)


def tool_start_hippo2_index(args: dict) -> dict:
    cfg = load_config()
    ds = _require_str(args, "dataset_id") or ""
    return text_result(
        job_manager.start_job(
            cfg,
            job_type="hippo2_index",
            args=args,
            dataset_id=ds,
            runner=lambda _job_id: _run_hippo2_index(cfg, args, document=False),
        )
    )


def tool_hippo2_index_document(args: dict) -> dict:
    cfg = load_config()
    try:
        return text_result(_run_hippo2_index(cfg, args, document=True))
    except Exception as exc:  # noqa: BLE001
        return text_result(f"hippo2_index_document failed: {exc}", is_error=True)


def tool_start_hippo2_index_document(args: dict) -> dict:
    cfg = load_config()
    doc_id = _require_str(args, "document_id") or ""
    return text_result(
        job_manager.start_job(
            cfg,
            job_type="hippo2_index_document",
            args=args,
            document_id=doc_id,
            runner=lambda _job_id: _run_hippo2_index(cfg, args, document=True),
        )
    )


def tool_hippo2_refresh_synonyms(_args: dict) -> dict:
    cfg = load_config()
    try:
        with silenced_stdout():
            with storage.sqlite_session(cfg) as sconn:
                result = hippo2_synonyms.rebuild_synonyms(sconn, cfg.hippo2)
                retriever_graph.mark_dirty(sconn)
        _ppr_engine(cfg).invalidate()
    except Exception as exc:  # noqa: BLE001
        return text_result(f"hippo2_refresh_synonyms failed: {exc}", is_error=True)
    return text_result({"status": "ok", **result})


def tool_hippo2_search(args: dict) -> dict:
    cfg = load_config()
    q = _require_str(args, "query")
    if not q:
        return text_result("query is required", is_error=True)
    dataset_ids = _resolve_datasets(args.get("dataset_ids"))
    top = _safe_int(args, "top_n", cfg.hippo2.top_chunks, lo=1, hi=100)
    try:
        with silenced_stdout():
            data = retriever_api.hybrid_search(
                cfg,
                q,
                dataset_ids,
                pipeline="hippo2",
                top=top,
                top_k=max(top, _safe_int(args, "top_k", 200, lo=1, hi=500)),
            )
    except Exception as exc:  # noqa: BLE001
        return text_result(f"hippo2_search failed: {exc}", is_error=True)
    return text_result({
        "query": q,
        "dataset_ids": dataset_ids,
        "pipeline": "hippo2",
        "total": data["total"],
        "chunks": data["items"],
    })


def tool_hippo2_stats(_args: dict) -> dict:
    cfg = load_config()
    try:
        with silenced_stdout():
            with storage.sqlite_session(cfg) as sconn:
                counts = {
                    "passages": sconn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
                    "entities": sconn.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
                    "triples": sconn.execute("SELECT COUNT(*) FROM triples").fetchone()[0],
                    "mentions": sconn.execute("SELECT COUNT(*) FROM chunk_mentions").fetchone()[0],
                    "synonyms": sconn.execute("SELECT COUNT(*) FROM entity_synonyms").fetchone()[0],
                    "entity_embeddings": sconn.execute("SELECT COUNT(*) FROM entity_embeddings").fetchone()[0],
                    "fact_embeddings": sconn.execute("SELECT COUNT(*) FROM fact_embeddings").fetchone()[0],
                    "cached_extractions": sconn.execute("SELECT COUNT(*) FROM extraction_cache").fetchone()[0],
                }
                dirty = retriever_graph.is_dirty(sconn)
                last_index = retriever_graph.get_state(sconn, "last_index_at", "")
                last_rebuild = retriever_graph.get_state(sconn, "last_rebuilt_at", "")
                checksum = retriever_graph.graph_checksum(sconn)
                warm = _ppr_engine(cfg).warm(sconn)
    except Exception as exc:  # noqa: BLE001
        return text_result(f"hippo2_stats failed: {exc}", is_error=True)
    return text_result({
        "counts": counts,
        "graph_dirty": dirty,
        "last_index_at": last_index,
        "last_rebuilt_at": last_rebuild,
        "checksum": checksum,
        "ppr": warm,
    })


# ----- benchmark ----------------------------------------------------------

# Test queries with expected keywords per topic document.
# Each entry: (query, [expected_keywords_any_of_which_counts_as_hit])
_BENCHMARK_QA: list[tuple[str, list[str]]] = [
    (
        "How does RAG retrieval work with hybrid search?",
        ["retrieval", "hybrid", "BM25", "vector", "RRF", "fusion", "embedding"],
    ),
    (
        "What is the role of vector databases in semantic search?",
        ["vector", "embedding", "similarity", "Qdrant", "FAISS", "ANN", "HNSW"],
    ),
    (
        "Explain the query key value attention mechanism in transformers",
        ["attention", "query", "key", "value", "transformer", "QKV", "self-attention"],
    ),
    (
        "What tools and agents does LangChain provide?",
        ["LangChain", "agent", "chain", "tool", "memory", "LCEL"],
    ),
    (
        "What metrics are used to evaluate RAG pipeline accuracy?",
        ["RAGAS", "faithfulness", "precision", "recall", "NDCG", "MRR", "relevance"],
    ),
]

_BENCHMARK_DOCS_DIR = (
    Path(__file__).resolve().parent.parent / "test_data" / "benchmark_docs"
)

# Pipelines that require external models/APIs and are marked as best-effort.
_EXTERNAL_MODEL_PIPELINES = frozenset({
    "rrf_rerank", "rrf_llm_rerank", "rrf_graph_rerank", "hippo2_graph_rrf", "hippo2",
})


def _hit_rate(contexts: list[dict], expected_keywords: list[str]) -> bool:
    """Return True if any expected keyword appears in any retrieved context."""
    combined = " ".join(c.get("text", "") for c in contexts).lower()
    return any(kw.lower() in combined for kw in expected_keywords)


def _run_benchmark_pipelines(cfg, args: dict, job_id: str | None = None) -> dict:
    """Ingest BEIR NFCorpus, run queries, measure accuracy + speed, return report."""
    requested = args.get("pipelines")
    if isinstance(requested, list) and requested:
        pipelines_to_test = [str(p) for p in requested if str(p).strip()]
    else:
        from retriever.pipelines import profiles as _pp
        _pp.sync_with_disk(cfg)
        pipelines_to_test = _pp.names()

    prefix = str(args.get("dataset_id_prefix") or "beir_nf").strip() or "beir_nf"
    top_n = _safe_int(args, "top_n", 10, lo=1, hi=100)
    cleanup = bool(args.get("cleanup", True))

    import tempfile
    import os
    import time
    from beir import util
    from beir.datasets.data_loader import GenericDataLoader
    from pytrec_eval import RelevanceEvaluator

    report = {"pipelines": {}, "summary": []}
    created_datasets = []

    if job_id:
        _job_progress(cfg, job_id, 2, "Downloading BEIR dataset...")

    # 1. Download BEIR dataset
    dataset = "nfcorpus"
    url = "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/{}.zip".format(dataset)
    out_dir = os.path.join(tempfile.gettempdir(), "beir_datasets")
    data_path = util.download_and_unzip(url, out_dir)
    corpus, queries, qrels = GenericDataLoader(data_path).load(split="test")
    
    if job_id:
        _job_progress(cfg, job_id, 10, "Extracting text files for upload...")

    # 2. Generate text files for upload
    docs_dir = Path(tempfile.gettempdir()) / "nfcorpus_docs"
    if not docs_dir.exists():
        docs_dir.mkdir(parents=True)
        for doc_id, doc in corpus.items():
            text = f"{doc.get('title', '')}\n\n{doc.get('text', '')}"
            file_path_doc = docs_dir / f"{doc_id}.txt"
            file_path_doc.write_text(text, encoding="utf-8")

    total_pipelines = len(pipelines_to_test)
    for idx, pipeline in enumerate(pipelines_to_test):
        if job_id:
            base_prog = 10 + (80 * idx // total_pipelines)
            _job_progress(cfg, job_id, base_prog, f"Pipeline {idx+1}/{total_pipelines}: Ingesting {pipeline}...")

        dataset_id = f"{prefix}_{pipeline}"
        created_datasets.append(dataset_id)
        entry = {"pipeline": pipeline, "dataset_id": dataset_id}

        # --- ingest ---
        ingest_start = time.time()
        try:
            with storage.sqlite_session(cfg) as conn:
                storage.ensure_dataset(conn, dataset_id, f"Benchmark [{pipeline}]", "")
                storage.update_dataset_metadata(
                    conn, dataset_id, {"preferred_search_pipeline": pipeline}
                )
            ingest_result = _run_upload_directory(
                cfg,
                {
                    "dataset_id": dataset_id,
                    "dir_path": str(docs_dir),
                    "pipeline": pipeline,
                    "async": False,
                },
            )
            ingest_elapsed = time.time() - ingest_start
            entry["ingest_seconds"] = round(ingest_elapsed, 3)
            entry["ingest_docs"] = ingest_result.get("processed_count", 0)
            entry["ingest_errors"] = ingest_result.get("error_count", 0)
            if ingest_result.get("error_count", 0) > 0 and ingest_result.get("processed_count", 0) == 0:
                entry["status"] = "ingest_failed"
                report["pipelines"][pipeline] = entry
                continue
        except Exception as exc:
            entry["status"] = "ingest_failed"
            entry["error"] = str(exc)[:200]
            report["pipelines"][pipeline] = entry
            continue

        if job_id:
            _job_progress(cfg, job_id, base_prog + (80 // total_pipelines // 2), f"Pipeline {idx+1}/{total_pipelines}: Searching {pipeline}...")

        # --- search ---
        pipeline_run = {}
        q_latencies = []
        for query_id, query_text in queries.items():
            if query_id not in qrels:
                continue
            q_start = time.time()
            try:
                with silenced_stdout():
                    raw = retriever_api.hybrid_search(
                        cfg,
                        query_text,
                        [dataset_id],
                        pipeline=pipeline,
                        top=top_n,
                        top_k=max(top_n * 10, 50),
                    )
                q_elapsed = time.time() - q_start
                q_latencies.append(q_elapsed)
                
                res = {}
                for rank, item in enumerate(raw.get("items", [])):
                    doc_name = item.get("document_name", "")
                    doc_id_match = doc_name.replace(".txt", "")
                    if doc_id_match not in res:
                        res[doc_id_match] = item.get("similarity", 0.0)
                pipeline_run[query_id] = res
            except Exception as exc:
                pass
        
        # --- Evaluation ---
        evaluator = RelevanceEvaluator(qrels, {'ndcg_cut.10', 'map_cut.10', 'recall.10', 'P.10'})
        metrics = evaluator.evaluate(pipeline_run)
        
        if metrics:
            ndcg_10 = sum(q.get('ndcg_cut_10', 0) for q in metrics.values()) / len(metrics)
            map_10 = sum(q.get('map_cut_10', 0) for q in metrics.values()) / len(metrics)
            recall_10 = sum(q.get('recall_10', 0) for q in metrics.values()) / len(metrics)
            p_10 = sum(q.get('P_10', 0) for q in metrics.values()) / len(metrics)
        else:
            ndcg_10 = map_10 = recall_10 = p_10 = 0.0
            
        avg_latency = round(sum(q_latencies) / len(q_latencies) * 1000, 1) if q_latencies else None

        entry.update({
            "status": "ok",
            "ndcg_10": round(ndcg_10, 4),
            "map_10": round(map_10, 4),
            "recall_10": round(recall_10, 4),
            "p_10": round(p_10, 4),
            "avg_latency_ms": avg_latency,
            "total_queries": len(pipeline_run),
        })
        report["pipelines"][pipeline] = entry

    if job_id:
        _job_progress(cfg, job_id, 95, "Cleaning up...")

    # --- cleanup ---
    if cleanup:
        for ds in created_datasets:
            try:
                with storage.sqlite_session(cfg) as conn:
                    conn.execute("DELETE FROM chunk_fts WHERE dataset_id = ?", (ds,))
                    conn.execute("DELETE FROM chunks WHERE dataset_id = ?", (ds,))
                    conn.execute("DELETE FROM documents WHERE dataset_id = ?", (ds,))
                    conn.execute("DELETE FROM datasets WHERE dataset_id = ?", (ds,))
                import shutil
                shutil.rmtree(cfg.dataset_dir(ds), ignore_errors=True)
            except Exception:
                pass
        report["cleanup"] = "datasets removed"
    else:
        report["cleanup"] = "datasets retained (pass cleanup=true to remove)"

    # --- markdown report ---
    lines = ["# BEIR NFCorpus RAG Benchmark Report", ""]
    lines.append(f"Queries per pipeline: {len(qrels)}, top_n={top_n}")
    lines.append("")
    lines.append("| Pipeline | Status | Ingest(s) | Avg Latency(ms) | NDCG@10 | MAP@10 | Recall@10 | P@10 |")
    lines.append("|----------|--------|-----------|-----------------|---------|--------|-----------|------|")
    for pipeline, e in report["pipelines"].items():
        status = e.get("status", "?")
        ingest = f"{e['ingest_seconds']:.2f}" if "ingest_seconds" in e else "—"
        latency = f"{e['avg_latency_ms']:.0f}" if e.get("avg_latency_ms") is not None else "—"
        if status == "ok":
            ndcg = f"{e['ndcg_10']:.4f}"
            map_val = f"{e['map_10']:.4f}"
            recall = f"{e['recall_10']:.4f}"
            p10 = f"{e['p_10']:.4f}"
            lines.append(f"| {pipeline} | {status} | {ingest} | {latency} | {ndcg} | {map_val} | {recall} | {p10} |")
        else:
            lines.append(f"| {pipeline} | {status} | {ingest} | {latency} | — | — | — | — |")

    report["markdown"] = "\n".join(lines)
    report["summary"] = {
        "total_pipelines": len(pipelines_to_test),
        "ok": sum(1 for e in report["pipelines"].values() if e.get("status") == "ok"),
        "failed": sum(1 for e in report["pipelines"].values() if e.get("status") != "ok"),
    }

    return report

def tool_start_benchmark_pipelines(args: dict) -> dict:
    cfg = load_config()
    job = job_manager.start_job(
        cfg,
        job_type="benchmark_pipelines",
        args=args,
        runner=lambda job_id: _run_benchmark_pipelines(cfg, args, job_id=job_id),
    )
    return text_result(job)

def tool_benchmark_pipelines(args: dict) -> dict:
    cfg = load_config()
    run_async = bool(args.get("async", True))
    if run_async:
        return tool_start_benchmark_pipelines(args)
    return text_result(_run_benchmark_pipelines(cfg, args))


HANDLERS = {
    "search": tool_search,
    "list_datasets": tool_list_datasets,
    "get_dataset": tool_get_dataset,
    "create_dataset": tool_create_dataset,
    "delete_dataset": tool_delete_dataset,
    "upload": tool_upload,
    "get_job": tool_get_job,
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
    "admin_help": tool_admin_help,
    "graph_query": tool_graph_query,
    "graph_rebuild": tool_graph_rebuild,
    "hippo2_index": tool_hippo2_index,
    "start_hippo2_index": tool_start_hippo2_index,
    "hippo2_index_document": tool_hippo2_index_document,
    "hippo2_refresh_synonyms": tool_hippo2_refresh_synonyms,
    "hippo2_search": tool_hippo2_search,
    "hippo2_stats": tool_hippo2_stats,
    "pipeline_tutorial": tool_pipeline_tutorial,
    "start_benchmark_pipelines": tool_start_benchmark_pipelines,
    "benchmark_pipelines": tool_benchmark_pipelines,
}
