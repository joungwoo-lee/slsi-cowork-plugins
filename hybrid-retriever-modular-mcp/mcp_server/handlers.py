"""Tool handlers — one function per MCP tool. All call the retriever HTTP API.

Each handler:
  - Validates required arguments and returns text_result(..., is_error=True)
    on bad input.
  - Calls http_request() (stdlib urllib) for plain JSON endpoints.
  - For `upload_document` only, falls back to a tiny multipart/form-data
    encoder built in-process (also stdlib only) so the MCP has zero third-
    party Python deps.
  - Returns a tool-result dict (TextContent block).
  - Lets exceptions propagate; dispatch.handle_tools_call converts them to
    isError responses with the traceback on stderr.
"""
from __future__ import annotations

import mimetypes
import os
import secrets
from pathlib import Path
from typing import Any

from . import bootstrap
from .protocol import text_result
from .runtime import RetrieverHttpError, http_request, silenced_stdout


def _resolve_datasets(arg: Any) -> list[str]:
    if isinstance(arg, list) and arg:
        return [str(x) for x in arg if str(x).strip()]
    return list(bootstrap.DEFAULT_DATASET_IDS)


def _http_error(exc: RetrieverHttpError) -> dict:
    payload: dict[str, Any] = {"error": str(exc)}
    if exc.status is not None:
        payload["status"] = exc.status
    if exc.body is not None:
        payload["body"] = exc.body
    return text_result(payload, is_error=True)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
def tool_search(args: dict) -> dict:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        return text_result("query is required and must be a non-empty string", is_error=True)

    datasets = _resolve_datasets(args.get("dataset_ids"))
    if not datasets:
        return text_result(
            "dataset_ids is empty. Pass `dataset_ids` explicitly or set the "
            "RETRIEVER_DEFAULT_DATASETS env var (comma-separated).",
            is_error=True,
        )

    top_n = max(1, min(50, int(args.get("top_n", 12))))
    payload: dict[str, Any] = {
        "question": query.strip(),
        "query": query.strip(),
        "dataset_ids": datasets,
        "keyword": bool(args.get("keyword", True)),
        "vector_similarity_weight": float(args.get("vector_similarity_weight", 0.5)),
        "similarity_threshold": float(args.get("similarity_threshold", 0.0)),
        "top_k": int(args.get("top_k", 200)),
        "page": int(args.get("page", 1)),
        "page_size": int(args.get("page_size", 100)),
    }
    if args.get("rerank_id"):
        payload["rerank_id"] = args["rerank_id"]
    if args.get("pipeline_name"):
        payload["pipeline_name"] = args["pipeline_name"]
    if isinstance(args.get("metadata_condition"), dict):
        payload["metadata_condition"] = args["metadata_condition"]

    try:
        with silenced_stdout():
            resp = http_request("POST", "/api/v1/retrieval", json_body=payload)
    except RetrieverHttpError as exc:
        return _http_error(exc)

    data = (resp or {}).get("data") or {}
    items_any = data.get("items") or data.get("chunks") or []
    if not isinstance(items_any, list):
        items_any = []
    items = items_any[:top_n]

    contexts: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    for c in items:
        if not isinstance(c, dict):
            continue
        pos = c.get("position")
        if pos is None and isinstance(c.get("positions"), list) and c["positions"]:
            pos = c["positions"][0]

        def _f(x: Any) -> float:
            try:
                return float(x)
            except (TypeError, ValueError):
                return 0.0

        contexts.append({
            "text": c.get("content", ""),
            "source": {
                "dataset_id": c.get("dataset_id"),
                "document_id": c.get("document_id"),
                "document_name": c.get("document_name") or c.get("name"),
                "position": pos,
                "chunk_id": c.get("id"),
                "similarity": _f(c.get("similarity")),
                "vector_similarity": _f(c.get("vector_similarity")),
                "term_similarity": _f(c.get("term_similarity")),
            },
        })
        citations.append({
            "document_name": c.get("document_name") or c.get("name"),
            "position": pos,
            "score": _f(c.get("similarity")),
            "chunk_id": c.get("id"),
        })

    return text_result({
        "query": query.strip(),
        "dataset_ids": datasets,
        "total": data.get("total", len(items_any)),
        "page": data.get("page"),
        "page_size": data.get("page_size"),
        "contexts": contexts,
        "citations": citations,
    })


# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------
def tool_list_datasets(_args: dict) -> dict:
    try:
        resp = http_request("GET", "/api/v1/datasets")
    except RetrieverHttpError as exc:
        return _http_error(exc)
    return text_result((resp or {}).get("data") or resp)


def tool_get_dataset(args: dict) -> dict:
    ds = args.get("dataset_id")
    if not isinstance(ds, str) or not ds:
        return text_result("dataset_id is required", is_error=True)
    try:
        resp = http_request("GET", f"/api/v1/datasets/{ds}")
    except RetrieverHttpError as exc:
        return _http_error(exc)
    return text_result((resp or {}).get("data") or resp)


def tool_create_dataset(args: dict) -> dict:
    name = args.get("name")
    if not isinstance(name, str) or not name.strip():
        return text_result("name is required", is_error=True)
    form: dict[str, Any] = {"name": name.strip()}
    if isinstance(args.get("description"), str):
        form["description"] = args["description"]
    try:
        resp = http_request("POST", "/api/v1/datasets", form=form)
    except RetrieverHttpError as exc:
        return _http_error(exc)
    return text_result((resp or {}).get("data") or resp)


def tool_delete_dataset(args: dict) -> dict:
    ds = args.get("dataset_id")
    if not isinstance(ds, str) or not ds:
        return text_result("dataset_id is required", is_error=True)
    try:
        resp = http_request("DELETE", f"/api/v1/datasets/{ds}")
    except RetrieverHttpError as exc:
        return _http_error(exc)
    return text_result((resp or {}).get("data") or resp)


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
def _encode_multipart(
    fields: dict[str, str],
    file_field: str,
    filename: str,
    file_bytes: bytes,
    content_type: str,
) -> tuple[bytes, str]:
    """Build a multipart/form-data body with stdlib only.

    Avoids pulling in `requests` just for one upload endpoint.
    """
    boundary = "----retriever-mcp-" + secrets.token_hex(16)
    crlf = b"\r\n"
    parts: list[bytes] = []
    for key, val in fields.items():
        if val is None:
            continue
        parts.append(f"--{boundary}".encode())
        parts.append(
            f'Content-Disposition: form-data; name="{key}"'.encode()
        )
        parts.append(b"")
        parts.append(str(val).encode("utf-8"))
    parts.append(f"--{boundary}".encode())
    parts.append(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"'.encode(
            "utf-8"
        )
    )
    parts.append(f"Content-Type: {content_type}".encode())
    parts.append(b"")
    parts.append(file_bytes)
    parts.append(f"--{boundary}--".encode())
    parts.append(b"")

    body = crlf.join(parts)
    return body, f"multipart/form-data; boundary={boundary}"


def tool_upload_document(args: dict) -> dict:
    ds = args.get("dataset_id")
    if not isinstance(ds, str) or not ds:
        return text_result("dataset_id is required", is_error=True)
    fp = args.get("file_path")
    if not isinstance(fp, str) or not fp:
        return text_result("file_path is required", is_error=True)

    path = Path(fp).expanduser()
    if not path.is_file():
        return text_result(f"file not found: {path}", is_error=True)
    size = path.stat().st_size
    if size == 0:
        return text_result(f"file is empty: {path}", is_error=True)

    mime, _ = mimetypes.guess_type(path.name)
    content_type = mime or "application/octet-stream"

    form: dict[str, Any] = {}
    if args.get("use_hierarchical") is not None:
        form["use_hierarchical"] = str(args["use_hierarchical"]).lower()
    if args.get("use_contextual") is not None:
        form["use_contextual"] = str(bool(args["use_contextual"])).lower()
    if isinstance(args.get("pipeline_name"), str) and args["pipeline_name"]:
        form["pipeline_name"] = args["pipeline_name"]

    with path.open("rb") as fh:
        file_bytes = fh.read()
    body, ctype = _encode_multipart(
        fields={k: str(v) for k, v in form.items()},
        file_field="file",
        filename=path.name,
        file_bytes=file_bytes,
        content_type=content_type,
    )

    try:
        with silenced_stdout():
            resp = http_request(
                "POST",
                f"/api/v1/datasets/{ds}/documents",
                raw_body=body,
                content_type=ctype,
                # Ingest is synchronous on the server side; allow a long timeout.
                timeout=max(bootstrap.REQUEST_TIMEOUT, 600.0),
            )
    except RetrieverHttpError as exc:
        return _http_error(exc)

    out = (resp or {}).get("data") or resp
    return text_result({
        "dataset_id": ds,
        "file": str(path),
        "size_bytes": size,
        "response": out,
    })


def tool_list_documents(args: dict) -> dict:
    ds = args.get("dataset_id")
    if not isinstance(ds, str) or not ds:
        return text_result("dataset_id is required", is_error=True)
    query = {
        "keywords": args.get("keywords"),
        "offset": int(args.get("offset", 0)),
        "limit": int(args.get("limit", 30)),
        "orderby": args.get("orderby", "created_at"),
        "desc": "true" if args.get("desc", True) else "false",
    }
    try:
        resp = http_request("GET", f"/api/v1/datasets/{ds}/documents", query=query)
    except RetrieverHttpError as exc:
        return _http_error(exc)
    return text_result((resp or {}).get("data") or resp)


def tool_get_document(args: dict) -> dict:
    ds = args.get("dataset_id")
    doc = args.get("document_id")
    if not isinstance(ds, str) or not ds:
        return text_result("dataset_id is required", is_error=True)
    if not isinstance(doc, str) or not doc:
        return text_result("document_id is required", is_error=True)
    try:
        resp = http_request("GET", f"/api/v1/datasets/{ds}/documents/{doc}")
    except RetrieverHttpError as exc:
        return _http_error(exc)
    return text_result((resp or {}).get("data") or resp)


def tool_list_chunks(args: dict) -> dict:
    ds = args.get("dataset_id")
    doc = args.get("document_id")
    if not isinstance(ds, str) or not ds:
        return text_result("dataset_id is required", is_error=True)
    if not isinstance(doc, str) or not doc:
        return text_result("document_id is required", is_error=True)
    query = {
        "keywords": args.get("keywords"),
        "offset": int(args.get("offset", 0)),
        "limit": int(args.get("limit", 30)),
    }
    try:
        resp = http_request(
            "GET", f"/api/v1/datasets/{ds}/documents/{doc}/chunks", query=query
        )
    except RetrieverHttpError as exc:
        return _http_error(exc)
    return text_result((resp or {}).get("data") or resp)


def tool_get_document_content(args: dict) -> dict:
    ds = args.get("dataset_id")
    doc = args.get("document_id")
    if not isinstance(ds, str) or not ds:
        return text_result("dataset_id is required", is_error=True)
    if not isinstance(doc, str) or not doc:
        return text_result("document_id is required", is_error=True)
    try:
        resp = http_request("GET", f"/api/v1/datasets/{ds}/documents/{doc}/content")
    except RetrieverHttpError as exc:
        return _http_error(exc)
    return text_result((resp or {}).get("data") or resp)


def tool_delete_document(args: dict) -> dict:
    ds = args.get("dataset_id")
    doc = args.get("document_id")
    if not isinstance(ds, str) or not ds:
        return text_result("dataset_id is required", is_error=True)
    if not isinstance(doc, str) or not doc:
        return text_result("document_id is required", is_error=True)
    try:
        resp = http_request("DELETE", f"/api/v1/datasets/{ds}/documents/{doc}")
    except RetrieverHttpError as exc:
        return _http_error(exc)
    return text_result((resp or {}).get("data") or resp)


# ---------------------------------------------------------------------------
# Pipelines + Diagnostics
# ---------------------------------------------------------------------------
def tool_list_pipelines(_args: dict) -> dict:
    try:
        resp = http_request("GET", "/api/v1/ingest-pipelines")
    except RetrieverHttpError as exc:
        return _http_error(exc)
    return text_result((resp or {}).get("data") or resp)


def tool_health(args: dict) -> dict:
    path = "/health" if args.get("shallow") else "/health/deep"
    try:
        resp = http_request("GET", path, timeout=10.0)
    except RetrieverHttpError as exc:
        return _http_error(exc)
    out = {"base_url": bootstrap.BASE_URL, "endpoint": path, "response": resp}
    return text_result(out)


# ---------------------------------------------------------------------------
# Registry consumed by dispatch.handle_tools_call
# ---------------------------------------------------------------------------
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
