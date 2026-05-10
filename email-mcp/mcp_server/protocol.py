"""JSON-RPC 2.0 framing helpers for the MCP stdio transport.

Spec: messages are individual JSON objects, newline-delimited, UTF-8, with
NO embedded newlines inside any single message. (See
https://modelcontextprotocol.io/specification/.../basic/transports.)

We use `json.dumps(..., separators=(",", ":"))` — compact, no real newlines.
String values containing "\\n" are escaped by json.dumps to the two-char
sequence backslash-n, so they never produce a literal LF in the wire format.

Any function in this module must NOT print to stdout for any reason except
writing a single MCP message via write_message().
"""
from __future__ import annotations

import json
import sys
from typing import Any


def write_message(obj: dict[str, Any]) -> None:
    """Serialise a single JSON-RPC message and flush it to stdout."""
    line = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def make_response(req_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def make_error(
    req_id: Any, code: int, message: str, data: Any | None = None
) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def text_result(payload: Any, *, is_error: bool = False) -> dict[str, Any]:
    """Build an MCP tool result with a single TextContent block.

    `payload` may be a str (used as-is) or any JSON-serialisable value
    (rendered as pretty JSON inside the text block, so the model can read
    structured data without needing structuredContent support).
    """
    if isinstance(payload, str):
        text = payload
    else:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    out: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        out["isError"] = True
    return out


# JSON-RPC standard error codes -------------------------------------------
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
