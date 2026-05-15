"""Stdio MCP server entry point for hybrid-retriever-modular-mcp.

INVOCATION: py -3 server.py   (or any Python >= 3.10)

Thin launcher: delegates to mcp_server.main(). Retrieval runs in-process using
local SQLite FTS5 and optional local Qdrant, so no FastAPI service is required.
"""
from __future__ import annotations

import sys
import os

# Ensure UTF-8 for MCP stdio communication on Windows
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')
if sys.stdin and hasattr(sys.stdin, 'reconfigure'):
    sys.stdin.reconfigure(encoding='utf-8')

try:
    from dotenv import load_dotenv
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    load_dotenv(env_path)
except ImportError:
    pass

from mcp_server import main

if __name__ == "__main__":
    sys.exit(main())
