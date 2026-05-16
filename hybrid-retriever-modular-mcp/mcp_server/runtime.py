"""Runtime utilities used by tool handlers."""
from __future__ import annotations

import contextlib
import sys
import threading


def log(msg: str) -> None:
    """Emit a log line to stderr. NEVER use print() to stdout — it would corrupt JSON-RPC."""
    print(f"[retriever-mcp] {msg}", file=sys.stderr, flush=True)


# Thread ids that are currently inside ``silenced_stdout()``. Writes from
# those threads go to stderr; writes from other threads pass through to the
# real stdout. This is critical when an async upload's background daemon
# is mid-pipeline while the main thread still needs to write JSON-RPC
# responses to stdout — a process-wide swap would corrupt the wire format.
_silenced_threads: set[int] = set()
_proxy_installed = False
_real_stdout = sys.stdout


class _ThreadAwareStdout:
    """sys.stdout proxy that routes writes per current-thread membership."""

    def __init__(self, real):
        self._real = real

    def write(self, s):
        if threading.get_ident() in _silenced_threads:
            return sys.stderr.write(s)
        return self._real.write(s)

    def flush(self):
        try:
            self._real.flush()
        except Exception:
            pass
        try:
            sys.stderr.flush()
        except Exception:
            pass

    def __getattr__(self, name):
        # Delegate anything else (encoding, isatty, fileno, ...) to the real stream.
        return getattr(self._real, name)


def _ensure_proxy() -> None:
    global _proxy_installed, _real_stdout
    if _proxy_installed:
        return
    _real_stdout = sys.stdout
    sys.stdout = _ThreadAwareStdout(_real_stdout)
    _proxy_installed = True


@contextlib.contextmanager
def silenced_stdout():
    """Thread-locally redirect stdout writes to stderr for the duration of a call.

    The JSON-RPC stream lives on the process stdout. A stray print() from
    any library inside a tool call would inject garbage into the wire
    format. We install a tiny per-thread routing proxy once, then the
    context manager just toggles the calling thread's membership in the
    silenced set — leaving other threads' stdout writes (including the
    main JSON-RPC dispatcher) untouched.
    """
    _ensure_proxy()
    tid = threading.get_ident()
    added = tid not in _silenced_threads
    if added:
        _silenced_threads.add(tid)
    try:
        yield
    finally:
        if added:
            _silenced_threads.discard(tid)
