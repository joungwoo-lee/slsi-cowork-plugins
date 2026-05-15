"""Entry point for hybrid-retriever-modular-mcp.

Default invocation keeps the existing stdio MCP server behaviour::

    py -3 server.py

To launch the local visual pipeline editor instead::

    py -3 server.py --editor

Retrieval runs in-process using local SQLite FTS5 and optional local Qdrant, so
no FastAPI service is required.
"""
from __future__ import annotations

import argparse
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

from mcp_server import main as mcp_main


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hybrid retriever MCP server")
    parser.add_argument(
        "--editor",
        action="store_true",
        help="Launch the local pipeline editor UI instead of the stdio MCP server.",
    )
    parser.add_argument(
        "--editor-port",
        type=int,
        default=8765,
        help="Preferred port for the pipeline editor (default: 8765).",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Start the pipeline editor without opening a browser window.",
    )
    return parser


def run(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.editor:
        from pipeline_editor import main as editor_main

        editor_argv: list[str] = ["--port", str(args.editor_port)]
        if args.no_browser:
            editor_argv.append("--no-browser")
        return editor_main(editor_argv)
    return mcp_main()

if __name__ == "__main__":
    sys.exit(run())
