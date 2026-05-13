"""retriever-mcp: stdio MCP server wrapping the hybrid_retriever HTTP API.

Module layout (mirrors email-mcp/mcp_server):
    bootstrap.py — stdout/stderr setup, base URL / API key / default datasets
                   resolution. Side-effects on import.
    protocol.py  — JSON-RPC 2.0 framing helpers (write_message, make_response,
                   make_error, text_result).
    runtime.py   — runtime utilities (silenced_stdout, env config accessor,
                   log to stderr, HTTP session factory).
    catalog.py   — TOOLS catalog (name, description, inputSchema for every
                   exposed MCP tool).
    handlers.py  — tool implementations against the RAGFlow-compatible REST
                   endpoints exposed by retriever_engine.
    dispatch.py  — JSON-RPC method dispatch loop (initialize, tools/list,
                   tools/call, ping, notifications).
"""
from __future__ import annotations

# bootstrap MUST run before anything else — it fixes stdout buffering for the
# JSON-RPC pipe and resolves base URL / auth config from env.
from . import bootstrap  # noqa: F401

from .dispatch import main

__all__ = ["main"]
