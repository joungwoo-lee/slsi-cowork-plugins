"""Side-effecting bootstrap: must be imported first.

Responsibilities (all happen at module import time):
1. Force UTF-8 + line-buffered stdout/stderr. Claude Desktop launches us as
   a subprocess; Python block-buffers piped stdout by default, which would
   stall JSON-RPC handshake until the buffer fills.
2. Resolve the retriever HTTP endpoint and credentials from environment
   variables. These are read here so handlers can stay stateless.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover — sys.stdout may already be wrapped
    pass

ROOT_PATH = Path(__file__).resolve().parent.parent

DEFAULT_BASE_URL = "http://127.0.0.1:9380"
DEFAULT_API_KEY = "ragflow-key"
DEFAULT_TIMEOUT_SEC = 60.0


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


BASE_URL = (os.getenv("RETRIEVER_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
API_KEY = os.getenv("RETRIEVER_API_KEY") or DEFAULT_API_KEY
DEFAULT_DATASET_IDS = _split_csv(os.getenv("RETRIEVER_DEFAULT_DATASETS"))
REQUEST_TIMEOUT = float(os.getenv("RETRIEVER_TIMEOUT_SEC") or DEFAULT_TIMEOUT_SEC)
VERIFY_SSL = (os.getenv("RETRIEVER_VERIFY_SSL") or "true").lower() not in ("0", "false", "no")
