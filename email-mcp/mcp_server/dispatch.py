"""JSON-RPC 2.0 dispatch loop.

main() reads newline-delimited JSON messages from stdin, routes each by
`method`, and writes responses (or nothing for notifications) to stdout via
protocol.write_message. Exceptions inside handlers are caught and turned
into either a tool isError result (for tools/call) or a JSON-RPC error
response (for everything else) ??never propagated, so the loop stays alive.
"""
from __future__ import annotations

import json
import sys
import traceback
from typing import Any, Callable, Optional

from .catalog import TOOLS
from .protocol import (
    INTERNAL_ERROR,
    METHOD_NOT_FOUND,
    make_error,
    make_response,
    text_result,
    write_message,
)
from .runtime import log

SERVER_NAME = "email-mcp"
SERVER_VERSION = "0.2.0"

SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
LATEST_PROTOCOL_VERSION = "2025-06-18"


# ---------------------------------------------------------------------------
# MCP method handlers
# ---------------------------------------------------------------------------
def handle_initialize(params: dict) -> dict:
    requested = params.get("protocolVersion", LATEST_PROTOCOL_VERSION)
    version = (
        requested if requested in SUPPORTED_PROTOCOL_VERSIONS else LATEST_PROTOCOL_VERSION
    )
    return {
        "protocolVersion": version,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
    }


def handle_tools_list(params: dict) -> dict:
    return {"tools": TOOLS}


# Required runtime dependencies (import-name as visible to Python).
# Kept in sync with requirements.txt. find_spec checks existence without
# importing, so a missing package here does not partially load anything.
REQUIRED_DEPS = (
    "pypff",
    "markdownify",
    "striprtf",
    "fitz",
    "docx",
    "openpyxl",
    "pptx",
    "qdrant_client",
    "requests",
    "dotenv",
)


def boot_doctor() -> Optional[str]:
    """Verify Python version and required dependencies at server startup.

    Returns None when the environment is ready. Returns a human-readable
    error string when something is wrong and cannot be auto-fixed.

    Missing packages trigger one attempt at install.ps1 -SkipClaudeConfig,
    followed by re-verification. importlib.util.find_spec is used instead
    of `import` to avoid partial-module side effects during the probe.
    """
    import importlib
    import importlib.util

    if sys.version_info[:2] != (3, 9):
        return (
            f"email-mcp requires Python 3.9 (64-bit), got "
            f"{sys.version.split()[0]} at {sys.executable}.\n"
            "Install Python 3.9.13 from "
            "https://www.python.org/ftp/python/3.9.13/python-3.9.13-amd64.exe"
        )

    def find_missing() -> list[str]:
        return [pkg for pkg in REQUIRED_DEPS if importlib.util.find_spec(pkg) is None]

    pending = find_missing()
    if not pending:
        return None

    log(f"boot doctor: missing dependencies {pending}; running install.ps1 ...")
    import subprocess
    from .bootstrap import ROOT_PATH

    script_path = ROOT_PATH / "install.ps1"
    if not script_path.exists():
        return (
            f"missing dependencies {pending} and install.ps1 not found at "
            f"{script_path}. Install manually: py -3.9 -m pip install -r "
            f"{ROOT_PATH / 'requirements.txt'}"
        )

    cmd = [
        "powershell.exe", "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", str(script_path),
        "-SkipClaudeConfig",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except Exception as exc:  # noqa: BLE001
        return f"install.ps1 execution failed: {exc}"
    if result.returncode != 0:
        return (
            f"install.ps1 exited with code {result.returncode}.\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

    importlib.invalidate_caches()
    pending = find_missing()
    if pending:
        return (
            f"install.ps1 reported success but these packages are still "
            f"missing after invalidate_caches: {pending}"
        )
    log("boot doctor: dependencies installed and verified")
    return None


def handle_tools_call(params: dict) -> dict:
    name = params.get("name", "")
    arguments = params.get("arguments") or {}

    try:
        from .handlers import HANDLERS
    except Exception as e:
        log(f"Failed to load tools: {e}")
        log(traceback.format_exc())
        return text_result(f"Failed to load tools: {e}\n{traceback.format_exc()}", is_error=True)

    handler = HANDLERS.get(name)
    if handler is None:
        return text_result(f"Unknown tool: {name}", is_error=True)
    try:
        return handler(arguments)
    except SystemExit:
        # Don't swallow ??let bootstrap-style asserts terminate the server.
        raise
    except Exception as exc:
        log(f"tool {name} failed: {exc}")
        log(traceback.format_exc())
        return text_result(f"{type(exc).__name__}: {exc}", is_error=True)


METHOD_HANDLERS: dict[str, Callable[[dict], dict]] = {
    "initialize": handle_initialize,
    "tools/list": handle_tools_list,
    "tools/call": handle_tools_call,
    "ping": lambda _params: {},
}


# ---------------------------------------------------------------------------
# Per-message dispatch
# ---------------------------------------------------------------------------
def dispatch(msg: dict) -> Optional[dict]:
    method = msg.get("method", "")
    msg_id = msg.get("id")

    # Notifications (notifications/initialized, notifications/cancelled, ??
    # MUST NOT receive a response, per spec.
    if isinstance(method, str) and method.startswith("notifications/"):
        return None

    handler = METHOD_HANDLERS.get(method)
    if handler is None:
        return make_error(msg_id, METHOD_NOT_FOUND, f"Method not found: {method}")

    try:
        result = handler(msg.get("params") or {})
        return make_response(msg_id, result)
    except Exception as exc:
        log(f"dispatch {method} failed: {exc}")
        log(traceback.format_exc())
        return make_error(msg_id, INTERNAL_ERROR, f"Internal error: {exc}")


# ---------------------------------------------------------------------------
# I/O loop
# ---------------------------------------------------------------------------
def main() -> int:
    # bootstrap.ROOT_PATH already validated; report it for log clarity.
    from .bootstrap import ROOT_PATH

    log(f"starting {SERVER_NAME} v{SERVER_VERSION} (email-mcp root at {ROOT_PATH})")

    err = boot_doctor()
    if err:
        log(f"boot doctor failed: {err}")
        print(f"[email-mcp boot error]\n{err}", file=sys.stderr, flush=True)
        return 1

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg: Any = json.loads(line)
        except json.JSONDecodeError as exc:
            log(f"bad JSON on stdin: {exc}")
            continue

        if isinstance(msg, list):
            # JSON-RPC 2.0 batch ??MCP doesn't use it but be tolerant.
            for sub in msg:
                if not isinstance(sub, dict):
                    continue
                resp = dispatch(sub)
                if resp is not None:
                    write_message(resp)
        elif isinstance(msg, dict):
            resp = dispatch(msg)
            if resp is not None:
                write_message(resp)
        else:
            log(f"ignoring non-object message: {msg!r}")

    log("stdin closed; exiting")
    return 0
