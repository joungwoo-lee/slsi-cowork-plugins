"""Stdio MCP server entry point for retriever-mcp.

INVOCATION: py -3 server.py   (or any Python >= 3.10)

Thin launcher — delegates to mcp_server.main(). The retriever-mcp is a pure
HTTP client to a running hybrid_retriever_windows_local FastAPI server, so it
has no native-extension constraints and works on any modern Python.
"""
from __future__ import annotations

import sys
from mcp_server import main

if __name__ == "__main__":
    sys.exit(main())
