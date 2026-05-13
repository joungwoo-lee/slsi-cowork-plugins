"""Side-effecting bootstrap: must be imported first.

Responsibilities (all happen at module import time, in order):
1. Force UTF-8 + line-buffered stdout/stderr. Claude Desktop launches us as
   a subprocess; Python block-buffers piped stdout by default, which would
   stall JSON-RPC handshake until the buffer fills.
2. Add the root `email-mcp` directory to sys.path so `from scripts.config import ...`
   works in handlers.

A wrong launch (missing dependencies, broken interpreter) MUST raise
SystemExit here ??better to die loudly at startup than to half-start and
fail mysteriously on the first tool call.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 1. stdout/stderr discipline ---------------------------------------------
# Stdio MCP transport: stdout carries JSON-RPC messages only, stderr carries
# logs. Reconfigure for UTF-8 (Korean subjects, paths) and line buffering
# (so each json.dumps + "\n" reaches the client without an explicit flush).
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover ??sys.stdout may already be wrapped
    pass

# 2. Add `scripts.*` importable path ---------------------------------------
# Path math: __file__ = email-mcp/mcp_server/bootstrap.py
#            .parent = mcp_server/
#            .parent.parent = email-mcp/
ROOT_PATH = Path(__file__).resolve().parent.parent

if not (ROOT_PATH / "scripts").is_dir():
    raise SystemExit(
        f"email-mcp: cannot find scripts directory at {ROOT_PATH / 'scripts'}\n"
        "Ensure email-mcp is installed correctly with its own scripts folder."
    )

sys.path.insert(0, str(ROOT_PATH))

# Sanity: import config module so a broken install fails at
# server startup, not on the first tool call. doctor() can still run after
# this because it inspects each dep individually with importlib.
from scripts.config import load_config as _ensure_loadable  # noqa: F401, E402
