"""Stdio MCP server entry point for hybrid-retriever-modular-mcp.

INVOCATION: py -3 server.py   (or any Python >= 3.10)

Thin launcher: delegates to mcp_server.main(). Retrieval runs in-process using
local SQLite FTS5 and optional local Qdrant, so no FastAPI service is required.
"""
from __future__ import annotations

import sys
from mcp_server import main

if __name__ == "__main__":
    sys.exit(main())
