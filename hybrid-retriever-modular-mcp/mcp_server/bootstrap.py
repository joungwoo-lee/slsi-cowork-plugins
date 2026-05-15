"""Side-effecting bootstrap: must be imported first.

Responsibilities (all happen at module import time):
1. Force UTF-8 + line-buffered stdout/stderr. Claude Desktop launches us as
   a subprocess; Python block-buffers piped stdout by default, which would
   stall JSON-RPC handshake until the buffer fills.
2. Resolve local retriever paths/default datasets from environment variables.
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
PYTHON_CMD = ("py", "-3.11")
PYTHON_CMD_DISPLAY = "py -3.11"


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


DEFAULT_DATASET_IDS = _split_csv(os.getenv("RETRIEVER_DEFAULT_DATASETS"))
