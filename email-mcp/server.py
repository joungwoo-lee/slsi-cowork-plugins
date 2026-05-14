"""Stdio MCP server entry point.

INVOCATION (Windows): py -3.9 server.py

Thin launcher ??delegates to mcp_server.main(). 
The Python 3.9 assertion is relaxed so that the server can start up and 
send a "Please install Python 3.9" message gracefully to the client
when tools are called, instead of just silently crashing at spawn.
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