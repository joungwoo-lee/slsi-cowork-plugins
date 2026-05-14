"""JSON-RPC 2.0 dispatch loop.

main() reads newline-delimited JSON messages from stdin, routes each by
`method`, and writes responses (or nothing for notifications) to stdout via
protocol.write_message. Exceptions inside handlers are caught and turned
into either a tool isError result (for tools/call) or a JSON-RPC error
response (for everything else) — never propagated, so the loop stays alive.
"""
from __future__ import annotations

import json
import sys
import traceback
from typing import Any, Callable, Optional

from . import bootstrap
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

SERVER_NAME = "retriever-mcp"
SERVER_VERSION = "0.1.0"

SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
LATEST_PROTOCOL_VERSION = "2025-06-18"


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


def handle_tools_list(_params: dict) -> dict:
    return {"tools": TOOLS}


def auto_install_check() -> Optional[dict]:
    """Lazy dependency check on first tool call.

    Tries to import every package the handlers depend on. If any is missing,
    invokes install.ps1 -SkipClaudeConfig once to fix it up. Mirrors the
    email-mcp pattern so a fresh PC needs only the MCP-registration .bat —
    actual dependency installation happens on first tool invocation.

    Returns a tool-result error dict on failure, or None when the environment
    is ready.
    """
    try:
        import dotenv  # noqa: F401
        import requests  # noqa: F401
        import qdrant_client  # noqa: F401
        import pypdf  # noqa: F401
        import docx  # noqa: F401  (python-docx ships as `docx`)
        import openpyxl  # noqa: F401
        import chardet  # noqa: F401
    except ImportError:
        import subprocess

        log("dependencies missing — auto-running install.ps1 ...")
        script_path = bootstrap.ROOT_PATH / "install.ps1"
        if not script_path.exists():
            return text_result(
                f"install.ps1 not found at {script_path}.\n"
                "Install manually: py -3 -m pip install -r requirements.txt",
                is_error=True,
            )
        cmd = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", str(script_path),
            "-SkipClaudeConfig",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode != 0:
                return text_result(
                    f"Auto-install failed (exit {result.returncode}).\n\n"
                    f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}",
                    is_error=True,
                )
        except Exception as exc:
            return text_result(f"install.ps1 execution failed: {exc}", is_error=True)
    return None


def handle_tools_call(params: dict) -> dict:
    name = params.get("name", "")
    arguments = params.get("arguments") or {}

    err_resp = auto_install_check()
    if err_resp:
        return err_resp

    try:
        from .handlers import HANDLERS
    except Exception as exc:
        log(f"failed to load handlers: {exc}")
        log(traceback.format_exc())
        return text_result(f"Failed to load tool handlers: {exc}", is_error=True)

    handler = HANDLERS.get(name)
    if handler is None:
        return text_result(f"Unknown tool: {name}", is_error=True)
    try:
        return handler(arguments)
    except SystemExit:
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


def dispatch(msg: dict) -> Optional[dict]:
    method = msg.get("method", "")
    msg_id = msg.get("id")

    # Notifications (notifications/initialized, notifications/cancelled, ...)
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


def main() -> int:
    log(
        f"starting {SERVER_NAME} v{SERVER_VERSION} "
        f"(backend=self-contained, default_datasets={bootstrap.DEFAULT_DATASET_IDS or '-'})"
    )
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
