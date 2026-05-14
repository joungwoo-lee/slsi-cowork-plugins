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


def canonical_tool_name(name: Any) -> str:
    """Normalise client-side tool-name variants to the server's catalog names.

    Some MCP clients expose tools as `<server>_<tool>` and LLMs occasionally
    echo a wrapped name with stray whitespace, e.g. `email_mcp_list_ mails`.
    Accept those forms by removing whitespace first, then stripping the known
    namespace prefix.
    """
    if not isinstance(name, str):
        return ""
    canonical = "".join(name.split())
    if canonical.startswith("email_mcp_"):
        canonical = canonical[len("email_mcp_"):]
    return canonical


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
    "urllib3",
    "win32api",
)

_BOOT_DOCTOR_OK = False
DEPS_PATH = None


import threading

_INSTALL_THREAD = None
_INSTALL_ERROR = None

def _install_worker(req_path):
    global _INSTALL_ERROR
    import subprocess
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--upgrade",
                "-r",
                str(req_path),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            _INSTALL_ERROR = (
                f"pip install exited with code {result.returncode}.\n"
                f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            )
        else:
            _INSTALL_ERROR = None
    except Exception as exc:
        _INSTALL_ERROR = f"pip install execution failed: {exc}"

def boot_doctor() -> Optional[str]:
    """Verify Python version and required dependencies at server startup.

    If missing, starts a background installation to avoid MCP timeouts (32001).
    """
    import importlib
    import importlib.util
    from .bootstrap import ROOT_PATH
    global _INSTALL_THREAD, _INSTALL_ERROR
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

    if _INSTALL_THREAD is not None:
        if _INSTALL_THREAD.is_alive():
            return f"Dependencies {pending} are installing in background... Please wait ~1 min and try again."
        
        if _INSTALL_ERROR:
            return f"Installation failed: {_INSTALL_ERROR}"

        importlib.invalidate_caches()
        pending = find_missing()
        if pending:
            return f"pip install finished but these packages are still missing: {pending}"
        return None

    log(f"boot doctor: missing dependencies {pending}; starting background pip install ...")
    req_path = ROOT_PATH / "requirements.txt"
    if not req_path.exists():
        return f"missing dependencies {pending} and requirements.txt not found at {req_path}"

    _INSTALL_ERROR = None
    _INSTALL_THREAD = threading.Thread(target=_install_worker, args=(req_path,), daemon=True)
    _INSTALL_THREAD.start()

    return f"Dependencies {pending} missing. A background installation has started. Please wait ~1 minute and try again."


def ensure_boot_ready() -> Optional[str]:
    """Run dependency repair once, but only after MCP has initialized."""
    global _BOOT_DOCTOR_OK
    if _BOOT_DOCTOR_OK:
        return None
    err = boot_doctor()
    if err is None:
        _BOOT_DOCTOR_OK = True
    return err


def handle_tools_call(params: dict) -> dict:
    name = params.get("name", "")
    arguments = params.get("arguments") or {}

    err = ensure_boot_ready()
    if err:
        log(f"boot doctor failed: {err}")
        return text_result(f"Dependency setup failed:\n{err}", is_error=True)

    try:
        from .handlers import HANDLERS
    except Exception as e:
        log(f"Failed to load tools: {e}")
        log(traceback.format_exc())
        return text_result(f"Failed to load tools: {e}\n{traceback.format_exc()}", is_error=True)

    canonical_name = canonical_tool_name(name)
    handler = HANDLERS.get(canonical_name)
    if handler is None:
        return text_result(f"Unknown tool: {name}", is_error=True)
    try:
        return handler(arguments)
    except SystemExit:
        # Don't swallow ??let bootstrap-style asserts terminate the server.
        raise
    except Exception as exc:
        log(f"tool {canonical_name or name} failed: {exc}")
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
