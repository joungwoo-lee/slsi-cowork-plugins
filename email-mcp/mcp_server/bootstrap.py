"""Side-effecting bootstrap: must be imported first.

Responsibilities (all happen at module import time, in order):
1. Force UTF-8 + line-buffered stdout/stderr. Claude Desktop launches us as
   a subprocess; Python block-buffers piped stdout by default, which would
   stall JSON-RPC handshake until the buffer fills.
2. Resolve EMAIL_CONNECTOR_PATH (env var override > sibling directory).
3. Add `<email-connector>/` to sys.path so `from scripts.config import ...`
   works in handlers.

A wrong launch (missing email-connector, broken interpreter) MUST raise
SystemExit here — better to die loudly at startup than to half-start and
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
except Exception:  # pragma: no cover — sys.stdout may already be wrapped
    pass

# 2. Locate the sibling email-connector skill -----------------------------
# Default: <email-mcp>/../email-connector/. Override with EMAIL_CONNECTOR_PATH.
# Path math: __file__ = email-mcp/mcp_server/bootstrap.py
#            .parent = mcp_server/
#            .parent.parent = email-mcp/
#            .parent.parent.parent = parent of email-mcp (e.g. plugins/)
DEFAULT_EC = Path(__file__).resolve().parent.parent.parent / "email-connector"
EC_PATH = Path(os.getenv("EMAIL_CONNECTOR_PATH", str(DEFAULT_EC))).resolve()

if not (EC_PATH / "scripts").is_dir():
    raise SystemExit(
        f"email-mcp: cannot find email-connector at {EC_PATH}\n"
        "Set EMAIL_CONNECTOR_PATH env var to the email-connector folder, or place\n"
        "email-mcp next to email-connector (e.g. both under %USERPROFILE%\\.claude\\skills\\)."
    )

# 3. Make `scripts.*` importable -------------------------------------------
sys.path.insert(0, str(EC_PATH))

# Sanity: import config module so a broken email-connector install fails at
# server startup, not on the first tool call. doctor() can still run after
# this because it inspects each dep individually with importlib.
from scripts.config import load_config as _ensure_loadable  # noqa: F401, E402
