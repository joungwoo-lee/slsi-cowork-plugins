"""email-mcp: stdio MCP server wrapping the email-connector skill.

Module layout (mirrors email-connector/scripts):
    bootstrap.py — Python 3.9 guard, stdout/stderr setup, sibling email-connector
                   path discovery. Side-effects on import.
    protocol.py  — JSON-RPC 2.0 framing helpers (write_message, make_response,
                   make_error, text_result).
    runtime.py   — runtime utilities used by handlers (_silenced_stdout to keep
                   stdout JSON-only, env path resolution, log to stderr).
    catalog.py   — TOOLS catalog (name, description, inputSchema for every
                   exposed MCP tool).
    handlers.py  — tool implementations bound to email-connector library
                   functions.
    dispatch.py  — JSON-RPC method dispatch loop (initialize, tools/list,
                   tools/call, ping, notifications).
"""
from __future__ import annotations

# bootstrap MUST run before anything else — it asserts Python 3.9, fixes
# stdout for the JSON-RPC pipe, and adds email-connector to sys.path.
from . import bootstrap  # noqa: F401

from .dispatch import main

__all__ = ["main"]
