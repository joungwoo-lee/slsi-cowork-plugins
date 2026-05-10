"""Stdio MCP server entry point.

INVOCATION (Windows): py -3.9 server.py

Thin launcher — delegates to mcp_server.main(). The Python 3.9 assertion
runs *before* the package import so a wrong-interpreter launch fails with
a clear message instead of an obscure ImportError from libpff.
"""
from __future__ import annotations

import sys

if sys.version_info[:2] != (3, 9):
    raise SystemExit(
        f"email-mcp requires Python 3.9 (got {sys.version_info.major}.{sys.version_info.minor} at {sys.executable}).\n"
        "email-connector pins libpff-python==20211114 (cp39-win_amd64 wheel only),\n"
        "so this MCP server must run on the same 3.9 interpreter to import its modules.\n"
        "Run with the launcher: py -3.9 server.py"
    )

from mcp_server import main

if __name__ == "__main__":
    sys.exit(main())
