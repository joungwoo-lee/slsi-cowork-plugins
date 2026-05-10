"""Stdio MCP server that exposes the email-connector skill as MCP tools.

Runs in the **same Python 3.9 interpreter** as email-connector and imports its
scripts in-process. The MCP Python SDK requires Python 3.10+, so this server
implements the JSON-RPC 2.0 / stdio transport from scratch using only the
standard library.

INVOCATION (Windows): py -3.9 server.py
"""
from __future__ import annotations

import sys
if sys.version_info[:2] != (3, 9):
    raise SystemExit(
        f"email-mcp requires Python 3.9 (got {sys.version_info.major}.{sys.version_info.minor} at {sys.executable}).\n"
        "email-connector pins libpff-python==20211114 (cp39-win_amd64 wheel only),\n"
        "so the MCP server must run on the same 3.9 interpreter to import its modules.\n"
        "Run with the launcher: py -3.9 server.py"
    )

# stdout MUST stay clean for JSON-RPC over stdio. Force UTF-8 + line buffering
# so messages flush immediately on a pipe (Claude Desktop launches us as a
# subprocess; Python block-buffers piped stdout by default).
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import contextlib
import json
import os
import traceback
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Locate the sibling email-connector skill
# ---------------------------------------------------------------------------
DEFAULT_EC = Path(__file__).resolve().parent.parent / "email-connector"
EC_PATH = Path(os.getenv("EMAIL_CONNECTOR_PATH", str(DEFAULT_EC))).resolve()

if not (EC_PATH / "scripts").is_dir():
    raise SystemExit(
        f"email-mcp: cannot find email-connector at {EC_PATH}\n"
        "Set EMAIL_CONNECTOR_PATH env var to the email-connector folder, or place\n"
        "email-mcp next to email-connector (e.g. both under %USERPROFILE%\\.claude\\skills\\)."
    )

# Make `scripts.*` importable from email-connector
sys.path.insert(0, str(EC_PATH))

from scripts.config import load_config  # noqa: E402
from scripts import search as ec_search  # noqa: E402
from scripts import doctor as ec_doctor  # noqa: E402
# convert/index pull in pst_extractor (libpff). Lazy-import inside the ingest
# handler so that doctor() can still run when libpff is not yet installed.

SERVER_NAME = "email-mcp"
SERVER_VERSION = "0.1.0"

SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
LATEST_PROTOCOL_VERSION = "2025-06-18"

# ---------------------------------------------------------------------------
# Tool catalog
# ---------------------------------------------------------------------------
TOOLS: list[dict[str, Any]] = [
    {
        "name": "search",
        "description": (
            "Hybrid keyword (SQLite FTS5) + semantic (Qdrant) search over an ingested "
            "PST archive. Returns ranked mail metadata (subject, sender, received, "
            "score, snippet, body_path). Read body_path with the read_mail tool to get "
            "the unified body+attachments markdown."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural-language or keyword query."},
                "mode": {
                    "type": "string",
                    "enum": ["hybrid", "keyword", "semantic"],
                    "default": "hybrid",
                    "description": "hybrid combines FTS5 + Qdrant; keyword-only or semantic-only also available.",
                },
                "top": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_mail",
        "description": (
            "Read the unified body.md (mail body + every attachment converted to markdown, "
            "in one file) for a given mail_id as returned by `search`. Returns the file's "
            "full UTF-8 contents."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "mail_id": {"type": "string"},
            },
            "required": ["mail_id"],
        },
    },
    {
        "name": "doctor",
        "description": (
            "Diagnose the email-connector install: Python 3.9 + 64-bit, Windows, all "
            "dependencies importable, .env present and populated, PST_PATH reachable, "
            "DATA_ROOT writable, embedding API reachable with the configured headers. "
            "Returns {all_ok, checks[]}. Run this first when anything fails."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "skip_api": {
                    "type": "boolean",
                    "default": False,
                    "description": "Skip the embedding API ping (saves a tiny token cost).",
                },
                "skip_pst": {
                    "type": "boolean",
                    "default": False,
                    "description": "Skip the PST_PATH existence check (use when configuring before the PST is in place).",
                },
            },
        },
    },
    {
        "name": "ingest",
        "description": (
            "Convert PST → per-mail body.md + meta.json (Phase 1) and index into "
            "SQLite FTS5 + Qdrant (Phase 2). LONG-RUNNING: the `limit` argument is "
            "REQUIRED here so MCP clients don't time out. For a full-PST run use the "
            "CLI directly: `py -3.9 scripts\\ingest.py`."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Max messages to convert in this batch.",
                },
                "skip_embedding": {
                    "type": "boolean",
                    "default": False,
                    "description": "Skip the embedding API + Qdrant; build SQLite FTS5 only.",
                },
                "skip_convert": {"type": "boolean", "default": False},
                "skip_index": {"type": "boolean", "default": False},
                "pst": {
                    "type": "string",
                    "description": "Override PST path. Default uses PST_PATH from .env.",
                },
            },
            "required": ["limit"],
        },
    },
]


# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------
def log(msg: str) -> None:
    print(f"[email-mcp] {msg}", file=sys.stderr, flush=True)


def write_message(obj: dict[str, Any]) -> None:
    # Spec: messages MUST NOT contain embedded newlines, MUST be UTF-8.
    # json.dumps without indent escapes \n inside strings, so the only way a raw
    # newline could appear is via separators — we use the compact form.
    line = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def make_response(req_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def make_error(req_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def text_result(payload: Any, *, is_error: bool = False) -> dict[str, Any]:
    """Wrap a Python value into an MCP tool result (one TextContent block)."""
    if isinstance(payload, str):
        text = payload
    else:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    out: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        out["isError"] = True
    return out


@contextlib.contextmanager
def _silenced_stdout():
    """Redirect stdout to stderr during tool execution.

    The JSON-RPC stream lives on stdout; any stray print() from a third-party
    library (qdrant, pypff, requests) would corrupt the protocol. We can't
    audit every transitive dep, so we shield the stream defensively.
    """
    saved = sys.stdout
    sys.stdout = sys.stderr
    try:
        yield
    finally:
        sys.stdout = saved


def _resolve_env_path() -> str:
    explicit = os.getenv("EMAIL_MCP_ENV")
    if explicit:
        return explicit
    return str(EC_PATH / ".env")


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------
def tool_search(args: dict) -> dict:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        return text_result("query is required and must be a non-empty string", is_error=True)
    mode = args.get("mode", "hybrid")
    if mode not in ("hybrid", "keyword", "semantic"):
        return text_result(f"invalid mode: {mode}", is_error=True)
    top = int(args.get("top", 10))
    cfg = load_config(_resolve_env_path())
    with _silenced_stdout():
        results = ec_search.hybrid_search(cfg, query, top=top, mode=mode)
    return text_result(results)


def tool_read_mail(args: dict) -> dict:
    mail_id = args.get("mail_id")
    if not isinstance(mail_id, str) or not mail_id:
        return text_result("mail_id is required", is_error=True)
    cfg = load_config(_resolve_env_path())
    body = cfg.body_md_path(mail_id)
    if not body.exists():
        return text_result(
            f"body.md not found for mail_id={mail_id} (looked at {body})", is_error=True
        )
    return text_result(body.read_text(encoding="utf-8", errors="replace"))


def tool_doctor(args: dict) -> dict:
    skip_api = bool(args.get("skip_api", False))
    skip_pst = bool(args.get("skip_pst", False))

    env_path = Path(_resolve_env_path())
    results: list[dict] = []
    results.append(ec_doctor.check_platform())
    results.append(ec_doctor.check_python_version())
    results.append(ec_doctor.check_python_bits())
    for import_name, pip_name in ec_doctor.DEPS:
        results.append(ec_doctor.check_dependency(import_name, pip_name))
    results.append(ec_doctor.check_env_file(env_path))

    cfg = load_config(env_path) if env_path.exists() else None
    if cfg is not None:
        cfg_check, cfg_ok = ec_doctor.check_config(cfg)
        results.append(cfg_check)
        if not skip_pst:
            results.append(ec_doctor.check_pst_path(cfg))
        if cfg_ok:
            results.append(ec_doctor.check_data_root(cfg))
            if not skip_api:
                with _silenced_stdout():
                    results.append(ec_doctor.check_embedding_api(cfg))

    all_ok = all(r["ok"] for r in results)
    return text_result({"all_ok": all_ok, "checks": results})


def tool_ingest(args: dict) -> dict:
    limit = args.get("limit")
    if limit is None:
        return text_result(
            "limit is required for in-MCP ingest. For a full-PST run, use the CLI: "
            "`py -3.9 scripts\\ingest.py`. The MCP tool is intended for incremental batches.",
            is_error=True,
        )
    skip_embedding = bool(args.get("skip_embedding", False))
    skip_convert = bool(args.get("skip_convert", False))
    skip_index = bool(args.get("skip_index", False))
    pst_override = args.get("pst")

    cfg = load_config(_resolve_env_path())
    # Lazy-import: pst_extractor needs libpff. If libpff isn't installed yet
    # (e.g. user is still running doctor to find out what's missing), this
    # import would crash server startup, breaking doctor too.
    from scripts import convert as ec_convert  # noqa: E402
    from scripts import index as ec_index  # noqa: E402

    converted = 0
    indexed = 0
    with _silenced_stdout():
        if not skip_convert:
            pst = pst_override or cfg.pst_path
            if not pst:
                return text_result(
                    "PST path missing: pass `pst` arg or set PST_PATH in .env", is_error=True
                )
            converted = ec_convert.run_convert(pst, cfg, limit=int(limit))
        if not skip_index:
            indexed = ec_index.run_index(cfg, skip_embedding=skip_embedding)

    return text_result(
        {
            "converted": converted,
            "indexed": indexed,
            "files_root": str(cfg.files_root),
            "db": str(cfg.db_path),
        }
    )


HANDLERS = {
    "search": tool_search,
    "read_mail": tool_read_mail,
    "doctor": tool_doctor,
    "ingest": tool_ingest,
}


# ---------------------------------------------------------------------------
# Method dispatch
# ---------------------------------------------------------------------------
def handle_initialize(params: dict) -> dict:
    requested = params.get("protocolVersion", LATEST_PROTOCOL_VERSION)
    version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else LATEST_PROTOCOL_VERSION
    return {
        "protocolVersion": version,
        "capabilities": {
            "tools": {"listChanged": False},
        },
        "serverInfo": {
            "name": SERVER_NAME,
            "version": SERVER_VERSION,
        },
    }


def handle_tools_list(params: dict) -> dict:
    return {"tools": TOOLS}


def handle_tools_call(params: dict) -> dict:
    name = params.get("name", "")
    arguments = params.get("arguments") or {}
    handler = HANDLERS.get(name)
    if handler is None:
        return text_result(f"Unknown tool: {name}", is_error=True)
    try:
        return handler(arguments)
    except SystemExit:
        raise
    except Exception as exc:
        log(f"tool {name} failed: {exc}")
        log(traceback.format_exc())
        return text_result(f"{type(exc).__name__}: {exc}", is_error=True)


METHOD_HANDLERS = {
    "initialize": handle_initialize,
    "tools/list": handle_tools_list,
    "tools/call": handle_tools_call,
    "ping": lambda params: {},
}


def dispatch(msg: dict) -> Optional[dict]:
    method = msg.get("method", "")
    msg_id = msg.get("id")

    # Notifications: spec says MUST NOT respond.
    if method.startswith("notifications/"):
        return None

    handler = METHOD_HANDLERS.get(method)
    if handler is None:
        return make_error(msg_id, -32601, f"Method not found: {method}")

    try:
        result = handler(msg.get("params") or {})
        return make_response(msg_id, result)
    except Exception as exc:
        log(f"dispatch {method} failed: {exc}")
        log(traceback.format_exc())
        return make_error(msg_id, -32603, f"Internal error: {exc}")


def main() -> int:
    log(f"starting {SERVER_NAME} v{SERVER_VERSION} (email-connector at {EC_PATH})")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as exc:
            log(f"bad JSON on stdin: {exc}")
            continue

        if isinstance(msg, list):
            # JSON-RPC batch (MCP doesn't use this, but be tolerant)
            for sub in msg:
                resp = dispatch(sub) if isinstance(sub, dict) else None
                if resp is not None:
                    write_message(resp)
        elif isinstance(msg, dict):
            resp = dispatch(msg)
            if resp is not None:
                write_message(resp)
        else:
            log(f"ignoring non-object message: {msg!r}")

    log("stdin closed; exiting")
    return 0


if __name__ == "__main__":
    sys.exit(main())
