from __future__ import annotations

import psutil


def _normalize_process_name(name: str) -> str:
    normalized = name.lower()
    return normalized[:-4] if normalized.endswith(".exe") else normalized


class ProcessWatchdog:
    def __init__(self, process_name: str, timeout_ms: int = 20000) -> None:
        self.process_name = _normalize_process_name(process_name)
        self.timeout_ms = timeout_ms
        self._pre_existing_pids = self._current_pids()
        self.tracked_pid: int | None = None

    def _current_pids(self) -> set[int]:
        current: set[int] = set()
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                name = proc.info.get("name")
                if name and _normalize_process_name(name) == self.process_name:
                    current.add(int(proc.info["pid"]))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return current

    def detect_new_process(self) -> None:
        new_pids = self._current_pids() - self._pre_existing_pids
        if new_pids:
            self.tracked_pid = sorted(new_pids)[0]

    def kill_if_running(self) -> None:
        if self.tracked_pid is None:
            return
        try:
            proc = psutil.Process(self.tracked_pid)
            children = proc.children(recursive=True)
            for child in children:
                try:
                    child.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            proc.kill()
            proc.wait(timeout=5)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
            return

    def __enter__(self) -> "ProcessWatchdog":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.kill_if_running()
