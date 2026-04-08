from __future__ import annotations

import os
import time

import pywintypes
import win32com.client


POLL_INTERVAL_SECONDS = 0.5


def log(message: str) -> None:
    print(message, file=__import__("sys").stderr)


def normalize_path(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def paths_match(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    return normalize_path(left) == normalize_path(right)


def wait_for_active_app(prog_id: str, timeout_seconds: float):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            return win32com.client.GetActiveObject(prog_id)
        except pywintypes.com_error:
            time.sleep(POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"{prog_id} instance was not available after {timeout_seconds:.0f}s.")


def wait_for_matching_document(collection, target_path: str, timeout_seconds: float, label: str):
    deadline = time.monotonic() + timeout_seconds
    normalized_target = normalize_path(target_path)

    while time.monotonic() < deadline:
        try:
            count = int(collection.Count)
            for index in range(1, count + 1):
                try:
                    item = collection.Item(index)
                    if paths_match(getattr(item, "FullName", None), normalized_target):
                        return item
                except Exception:
                    continue
        except Exception:
            pass
        time.sleep(POLL_INTERVAL_SECONDS)

    raise TimeoutError(f"{label} did not appear in the running Office app after {timeout_seconds:.0f}s.")


def wait_until_ready(check, timeout_seconds: float, timeout_message: str) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            if check():
                return
        except Exception:
            pass
        time.sleep(POLL_INTERVAL_SECONDS)
    raise TimeoutError(timeout_message)
