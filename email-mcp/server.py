"""Stdio MCP server entry point.

INVOCATION (Windows): py -3.9 server.py

Thin launcher ??delegates to mcp_server.main(). 
The Python 3.9 assertion is relaxed so that the server can start up and 
send a "Please install Python 3.9" message gracefully to the client
when tools are called, instead of just silently crashing at spawn.
"""
from __future__ import annotations

import sys
from mcp_server import main

if __name__ == "__main__":
    sys.exit(main())
