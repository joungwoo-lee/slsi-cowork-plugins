"""Runtime utilities used by tool handlers."""
from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path

from .bootstrap import EC_PATH


def log(msg: str) -> None:
    """Emit a log line to stderr. NEVER use print() to stdout — would corrupt JSON-RPC."""
    print(f"[email-mcp] {msg}", file=sys.stderr, flush=True)


def resolve_env_path() -> str:
    """Path to the .env that handlers should load.

    Override priority:
      1. EMAIL_MCP_ENV env var (explicit per-MCP override)
      2. <email-connector>/.env (default — same .env the skill uses)
    """
    explicit = os.getenv("EMAIL_MCP_ENV")
    if explicit:
        return explicit
    return str(EC_PATH / ".env")


@contextlib.contextmanager
def silenced_stdout():
    """Redirect stdout to stderr while a tool runs.

    The JSON-RPC stream lives on stdout. A stray print() from any third-party
    library (qdrant, pypff, requests, urllib3, ...) inside a tool call would
    inject garbage into the wire format and the client would disconnect. We
    can't audit every transitive dependency, so we route stdout writes to
    stderr (where they become visible logs) for the duration of the call.
    """
    saved = sys.stdout
    sys.stdout = sys.stderr
    try:
        yield
    finally:
        sys.stdout = saved
