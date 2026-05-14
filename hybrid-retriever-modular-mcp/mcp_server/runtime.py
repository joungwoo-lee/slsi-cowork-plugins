"""Runtime utilities used by tool handlers."""
from __future__ import annotations

import contextlib
import sys


def log(msg: str) -> None:
    """Emit a log line to stderr. NEVER use print() to stdout — it would corrupt JSON-RPC."""
    print(f"[retriever-mcp] {msg}", file=sys.stderr, flush=True)


@contextlib.contextmanager
def silenced_stdout():
    """Redirect stdout to stderr while a tool runs.

    The JSON-RPC stream lives on stdout. A stray print() from any library
    inside a tool call would inject garbage into the wire format and the
    client would disconnect. We route stdout writes to stderr (where they
    become visible logs) for the duration of the call.
    """
    saved = sys.stdout
    sys.stdout = sys.stderr
    try:
        yield
    finally:
        sys.stdout = saved
