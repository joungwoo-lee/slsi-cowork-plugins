"""Background job runner for long-running MCP tasks.

MCP requests should return quickly. These helpers persist job state in SQLite
and execute the heavy work on background daemon threads.
"""
from __future__ import annotations

import json
import threading
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from retriever import storage

_ACTIVE_JOBS: dict[str, threading.Thread] = {}
_LOCK = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def start_job(
    cfg,
    *,
    job_type: str,
    args: dict[str, Any],
    runner: Callable[[str], Any],
    dataset_id: str = "",
    document_id: str = "",
) -> dict[str, Any]:
    job_id = uuid.uuid4().hex
    submitted_at = _utc_now()
    with storage.sqlite_session(cfg) as conn:
        conn.execute(
            "INSERT INTO jobs(job_id, job_type, status, dataset_id, document_id, submitted_at, args_json) "
            "VALUES(?, ?, 'queued', ?, ?, ?, ?)",
            (job_id, job_type, dataset_id, document_id, submitted_at, _json(args)),
        )

    thread = threading.Thread(
        target=_run_job,
        args=(cfg, job_id, runner),
        name=f"retriever-job-{job_type}-{job_id[:8]}",
        daemon=True,
    )
    with _LOCK:
        _ACTIVE_JOBS[job_id] = thread
    thread.start()
    # Late import to avoid a circular reference at module load.
    from . import handlers as _h  # noqa: WPS433
    _h._reveal_and_notify("get_job")
    return {
        "job_id": job_id,
        "job_type": job_type,
        "status": "queued",
        "submitted_at": submitted_at,
        "next_step": f"Call get_job with job_id='{job_id}' to poll progress.",
        "next_action": {
            "tool": "get_job",
            "arguments": {"job_id": job_id},
            "use_when": "Poll until status='completed' or 'failed'.",
        },
    }


def _run_job(cfg, job_id: str, runner: Callable[[str], Any]) -> None:
    update_job(cfg, job_id, status="running", started_at=_utc_now(), progress=1, message="running")
    try:
        result = runner(job_id)
        update_job(
            cfg,
            job_id,
            status="completed",
            finished_at=_utc_now(),
            progress=100,
            message="completed",
            result=result,
            error_text="",
        )
    except Exception as exc:  # noqa: BLE001
        update_job(
            cfg,
            job_id,
            status="failed",
            finished_at=_utc_now(),
            message=str(exc),
            error_text="".join(traceback.format_exception_only(type(exc), exc)).strip(),
            result={"error": str(exc)},
        )
    finally:
        with _LOCK:
            _ACTIVE_JOBS.pop(job_id, None)


def update_job(
    cfg,
    job_id: str,
    *,
    status: str | None = None,
    progress: int | None = None,
    message: str | None = None,
    result: Any | None = None,
    error_text: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
) -> None:
    fields: list[str] = []
    params: list[Any] = []
    if status is not None:
        fields.append("status = ?")
        params.append(status)
    if progress is not None:
        fields.append("progress = ?")
        params.append(max(0, min(100, int(progress))))
    if message is not None:
        fields.append("message = ?")
        params.append(message)
    if result is not None:
        fields.append("result_json = ?")
        params.append(_json(result))
    if error_text is not None:
        fields.append("error_text = ?")
        params.append(error_text)
    if started_at is not None:
        fields.append("started_at = ?")
        params.append(started_at)
    if finished_at is not None:
        fields.append("finished_at = ?")
        params.append(finished_at)
    if not fields:
        return
    params.append(job_id)
    with storage.sqlite_session(cfg) as conn:
        conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE job_id = ?", params)


def get_job(cfg, job_id: str) -> dict[str, Any] | None:
    with storage.sqlite_session(cfg) as conn:
        row = conn.execute(
            "SELECT job_id, job_type, status, dataset_id, document_id, submitted_at, started_at, finished_at, "
            "progress, message, args_json, result_json, error_text FROM jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
    if not row:
        return None
    obj = {
        "job_id": row[0],
        "job_type": row[1],
        "status": row[2],
        "dataset_id": row[3],
        "document_id": row[4],
        "submitted_at": row[5],
        "started_at": row[6],
        "finished_at": row[7],
        "progress": int(row[8] or 0),
        "message": row[9] or "",
        "error": row[12] or "",
    }
    try:
        obj["args"] = json.loads(row[10] or "{}")
    except json.JSONDecodeError:
        obj["args"] = {}
    try:
        obj["result"] = json.loads(row[11]) if row[11] else None
    except json.JSONDecodeError:
        obj["result"] = row[11]
    return obj


def list_jobs(cfg, *, limit: int = 20, offset: int = 0, status: str = "") -> list[dict[str, Any]]:
    sql = (
        "SELECT job_id, job_type, status, dataset_id, document_id, submitted_at, started_at, finished_at, progress, message "
        "FROM jobs"
    )
    params: list[Any] = []
    if status:
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY submitted_at DESC LIMIT ? OFFSET ?"
    params.extend([int(limit), int(offset)])
    with storage.sqlite_session(cfg) as conn:
        rows = conn.execute(sql, params).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "job_id": row[0],
                "job_type": row[1],
                "status": row[2],
                "dataset_id": row[3],
                "document_id": row[4],
                "submitted_at": row[5],
                "started_at": row[6],
                "finished_at": row[7],
                "progress": int(row[8] or 0),
                "message": row[9] or "",
            }
        )
    return out
