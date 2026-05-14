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


# Required runtime dependencies (import-name as visible to Python).
# Kept in sync with requirements.txt.
REQUIRED_DEPS = (
    "dotenv",
    "requests",
    "qdrant_client",
    "pypdf",
    "docx",
    "openpyxl",
    "chardet",
    "urllib3",
)

_BOOT_DOCTOR_OK = False
DEPS_PATH = bootstrap.ROOT_PATH / ".mcp_deps"

if DEPS_PATH.exists():
    sys.path.insert(0, str(DEPS_PATH))


def boot_doctor() -> Optional[str]:
    """Verify required dependencies at server startup.

    Returns None when the environment is ready. Returns a human-readable
    error string when something is wrong and cannot be auto-fixed.

    Missing packages trigger one pip install into a local dependency directory,
    followed by re-verification. importlib.util.find_spec is used instead of
    `import` to avoid partial-module side effects during the probe.
    """
    import importlib
    import importlib.util

    def find_missing() -> list[str]:
        return [pkg for pkg in REQUIRED_DEPS if importlib.util.find_spec(pkg) is None]

    pending = find_missing()
    if not pending:
        return None

    log(f"boot doctor: missing dependencies {pending}; running pip install ...")
    import subprocess

    req_path = bootstrap.ROOT_PATH / "requirements.txt"
    if not req_path.exists():
        return (
            f"missing dependencies {pending} and requirements.txt not found at "
            f"{req_path}. Install manually: {sys.executable} -m pip install -r {req_path}"
        )

    DEPS_PATH.mkdir(parents=True, exist_ok=True)
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
                "--target",
                str(DEPS_PATH),
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except Exception as exc:  # noqa: BLE001
        return f"pip install execution failed: {exc}"
    if result.returncode != 0:
        return (
            f"pip install exited with code {result.returncode}.\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

    importlib.invalidate_caches()
    if str(DEPS_PATH) not in sys.path:
        sys.path.insert(0, str(DEPS_PATH))
    pending = find_missing()
    if pending:
        return (
            f"pip install reported success but these packages are still "
            f"missing after invalidate_caches: {pending}"
        )
    log("boot doctor: dependencies installed and verified")
    return None


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
