"""Tool handlers — one function per MCP tool. Bound to email-connector library calls.

Each handler:
  - Validates required arguments and returns text_result(..., is_error=True) on bad input.
  - Wraps any blocking work that might emit stdout in `silenced_stdout()`.
  - Returns a tool-result dict (TextContent block).
  - Lets exceptions propagate; dispatch.handle_tools_call converts them to
    isError responses with the traceback on stderr.

Lazy-import policy: convert.py / index.py pull in pst_extractor → libpff. If
libpff isn't installed yet (the user is still running `doctor` to find out),
top-level imports here would crash server startup. So we import those two
inside the handlers that need them.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.config import load_config  # email-connector (sys.path injected by bootstrap)
from scripts import doctor as ec_doctor
from scripts import search as ec_search
from scripts import storage as ec_storage

from .protocol import text_result
from .runtime import resolve_env_path, silenced_stdout


# ---------------------------------------------------------------------------
# Read-side tools
# ---------------------------------------------------------------------------
def tool_search(args: dict) -> dict:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        return text_result("query is required and must be a non-empty string", is_error=True)
    sender_like = args.get("sender_like")
    sender_not_like = args.get("sender_not_like")
    sender_exact = args.get("sender_exact")
    received_from = args.get("received_from")
    received_to = args.get("received_to")
    for key, value in {
        "sender_like": sender_like,
        "sender_not_like": sender_not_like,
        "sender_exact": sender_exact,
        "received_from": received_from,
        "received_to": received_to,
    }.items():
        if value is not None and not isinstance(value, str):
            return text_result(f"{key} must be a string", is_error=True)
    mode = args.get("mode", "hybrid")
    if mode not in ("hybrid", "keyword", "semantic"):
        return text_result(f"invalid mode: {mode}", is_error=True)
    top = int(args.get("top", 10))
    cfg = load_config(resolve_env_path())
    with silenced_stdout():
        results = ec_search.hybrid_search(
            cfg,
            query,
            top=top,
            mode=mode,
            sender_like=sender_like,
            sender_not_like=sender_not_like,
            sender_exact=sender_exact,
            received_from=received_from,
            received_to=received_to,
        )
    return text_result(
        {
            "display_instruction": (
                "User-facing display instruction: return the search results as a markdown table "
                "with exactly these columns in this order: 일련번호, 제목, 발신자, 수신일, 파일경로. "
                "Use body_path as the 파일경로 value. Do not read the mail body unless the user asks "
                "to inspect a specific result in more detail."
            ),
            "display_example": (
                "| 일련번호 | 제목 | 발신자 | 수신일 | 파일경로 |\n"
                "|---|---|---|---|---|\n"
                "| 1 | 회의 일정 | joung@samsung.com | 2026-05-12 | file:\\\\C:\\\\mail\\\\Files\\\\abc123\\\\body.md |"
            ),
            "results": results,
        }
    )


def tool_list_mails(args: dict) -> dict:
    sender_like = args.get("sender_like")
    subject_like = args.get("subject_like")
    limit = int(args.get("limit", 50))
    offset = int(args.get("offset", 0))
    if limit < 1 or limit > 500:
        return text_result("limit must be between 1 and 500", is_error=True)
    if offset < 0:
        return text_result("offset must be >= 0", is_error=True)

    cfg = load_config(resolve_env_path())
    sql = (
        "SELECT mail_id, subject, sender, received, body_path, has_vector "
        "FROM mail_metadata"
    )
    clauses: list[str] = []
    params: list[Any] = []
    if sender_like:
        clauses.append("LOWER(sender) LIKE ?")
        params.append(f"%{sender_like.lower()}%")
    if subject_like:
        clauses.append("LOWER(subject) LIKE ?")
        params.append(f"%{subject_like.lower()}%")
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY received DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with silenced_stdout(), ec_storage.sqlite_session(cfg) as conn:
        rows = conn.execute(sql, params).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM mail_metadata").fetchone()[0]

    return text_result(
        {
            "total_indexed": total,
            "returned": len(rows),
            "offset": offset,
            "limit": limit,
            "mails": [
                {
                    "mail_id": r[0],
                    "subject": r[1],
                    "sender": r[2],
                    "received": r[3],
                    "body_path": r[4],
                    "has_vector": bool(r[5]),
                }
                for r in rows
            ],
        }
    )


def tool_read_mail(args: dict) -> dict:
    mail_id = args.get("mail_id")
    if not isinstance(mail_id, str) or not mail_id:
        return text_result("mail_id is required", is_error=True)
    cfg = load_config(resolve_env_path())
    body = cfg.body_md_path(mail_id)
    if not body.exists():
        return text_result(
            f"body.md not found for mail_id={mail_id} (looked at {body})", is_error=True
        )
    return text_result(body.read_text(encoding="utf-8", errors="replace"))


def tool_read_meta(args: dict) -> dict:
    mail_id = args.get("mail_id")
    if not isinstance(mail_id, str) or not mail_id:
        return text_result("mail_id is required", is_error=True)
    cfg = load_config(resolve_env_path())
    meta_path = cfg.mail_dir(mail_id) / "meta.json"
    if not meta_path.exists():
        return text_result(
            f"meta.json not found for mail_id={mail_id} (looked at {meta_path})",
            is_error=True,
        )
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return text_result(f"meta.json is not valid JSON: {exc}", is_error=True)
    return text_result(meta)


def tool_read_attachment(args: dict) -> dict:
    mail_id = args.get("mail_id")
    if not isinstance(mail_id, str) or not mail_id:
        return text_result("mail_id is required", is_error=True)
    filename = args.get("filename")
    cfg = load_config(resolve_env_path())
    att_dir = cfg.attachments_dir(mail_id)
    if not att_dir.exists():
        return text_result(
            f"no attachments directory for mail_id={mail_id} (looked at {att_dir})",
            is_error=True,
        )

    if filename is None or filename == "":
        items = []
        for p in sorted(att_dir.iterdir()):
            if p.is_file():
                items.append({"filename": p.name, "size": p.stat().st_size})
        return text_result({"mail_id": mail_id, "attachments_dir": str(att_dir), "attachments": items})

    if not isinstance(filename, str):
        return text_result("filename must be a string", is_error=True)
    if "/" in filename or "\\" in filename or ".." in filename or filename.startswith("."):
        return text_result(
            "filename must be a plain name without path separators or leading dot",
            is_error=True,
        )

    target = att_dir / filename
    if not target.is_file():
        return text_result(f"attachment not found: {filename}", is_error=True)

    import mimetypes

    mime, _ = mimetypes.guess_type(filename)
    return text_result(
        {
            "mail_id": mail_id,
            "filename": filename,
            "path": str(target),
            "size": target.stat().st_size,
            "mime": mime or "application/octet-stream",
        }
    )


def tool_stats(args: dict) -> dict:
    cfg = load_config(resolve_env_path())
    out: dict[str, Any] = {
        "data_root": str(cfg.data_root),
        "files_root": str(cfg.files_root),
        "db_path": str(cfg.db_path),
        "vector_db_path": str(cfg.vector_db_path),
        "files_root_dirs": 0,
        "sqlite": {"total_mails": 0, "with_vector": 0},
    }
    if cfg.files_root.exists():
        out["files_root_dirs"] = sum(1 for d in cfg.files_root.iterdir() if d.is_dir())
    if cfg.db_path.exists():
        with silenced_stdout(), ec_storage.sqlite_session(cfg) as conn:
            (total,) = conn.execute("SELECT COUNT(*) FROM mail_metadata").fetchone()
            (with_vec,) = conn.execute(
                "SELECT COUNT(*) FROM mail_metadata WHERE has_vector=1"
            ).fetchone()
            out["sqlite"] = {"total_mails": total, "with_vector": with_vec}
    return text_result(out)


# ---------------------------------------------------------------------------
# Pipeline (write-side) tools
# ---------------------------------------------------------------------------
def tool_convert(args: dict) -> dict:
    limit = args.get("limit")
    if limit is None:
        return text_result(
            "limit is required for in-MCP convert. For a full PST, use the CLI: "
            "`py -3.9 scripts\\convert.py`.",
            is_error=True,
        )
    pst_override = args.get("pst")
    cfg = load_config(resolve_env_path())
    # Lazy-import: convert pulls in pst_extractor → libpff. If libpff is
    # missing, doctor() must still be callable to diagnose that.
    from scripts import convert as ec_convert  # noqa: E402

    pst = pst_override or cfg.pst_path
    if not pst:
        return text_result(
            "PST path missing: pass `pst` arg or set PST_PATH in .env", is_error=True
        )
    with silenced_stdout():
        n = ec_convert.run_convert(pst, cfg, limit=int(limit))
    return text_result({"converted": n, "files_root": str(cfg.files_root)})


def tool_index(args: dict) -> dict:
    skip_embedding = bool(args.get("skip_embedding", False))
    mail_ids = args.get("mail_ids")
    if mail_ids is not None and not (
        isinstance(mail_ids, list) and all(isinstance(x, str) for x in mail_ids)
    ):
        return text_result("mail_ids must be a list of strings", is_error=True)

    cfg = load_config(resolve_env_path())
    from scripts import index as ec_index  # noqa: E402

    with silenced_stdout():
        n = ec_index.run_index(cfg, skip_embedding=skip_embedding, mail_ids=mail_ids)
    return text_result({"indexed": n, "db": str(cfg.db_path)})


def tool_ingest(args: dict) -> dict:
    limit = args.get("limit")
    if limit is None:
        return text_result(
            "limit is required for in-MCP ingest. For a full-PST run, use the CLI: "
            "`py -3.9 scripts\\ingest.py`. The MCP tool is intended for incremental batches.",
            is_error=True,
        )
    skip_embedding = bool(args.get("skip_embedding", False))
    skip_convert = bool(args.get("skip_convert", False))
    skip_index = bool(args.get("skip_index", False))
    pst_override = args.get("pst")

    cfg = load_config(resolve_env_path())
    from scripts import convert as ec_convert  # noqa: E402
    from scripts import index as ec_index  # noqa: E402

    converted = 0
    indexed = 0
    with silenced_stdout():
        if not skip_convert:
            pst = pst_override or cfg.pst_path
            if not pst:
                return text_result(
                    "PST path missing: pass `pst` arg or set PST_PATH in .env",
                    is_error=True,
                )
            converted = ec_convert.run_convert(pst, cfg, limit=int(limit))
        if not skip_index:
            indexed = ec_index.run_index(cfg, skip_embedding=skip_embedding)

    return text_result(
        {
            "converted": converted,
            "indexed": indexed,
            "files_root": str(cfg.files_root),
            "db": str(cfg.db_path),
        }
    )


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------
def tool_doctor(args: dict) -> dict:
    skip_api = bool(args.get("skip_api", False))
    skip_pst = bool(args.get("skip_pst", False))

    env_path = Path(resolve_env_path())
    results: list[dict] = []
    results.append(ec_doctor.check_platform())
    results.append(ec_doctor.check_python_version())
    results.append(ec_doctor.check_python_bits())
    for import_name, pip_name in ec_doctor.DEPS:
        results.append(ec_doctor.check_dependency(import_name, pip_name))
    results.append(ec_doctor.check_env_file(env_path))

    cfg = load_config(env_path) if env_path.exists() else None
    if cfg is not None:
        cfg_check, cfg_ok = ec_doctor.check_config(cfg)
        results.append(cfg_check)
        if not skip_pst:
            results.append(ec_doctor.check_pst_path(cfg))
        if cfg_ok:
            results.append(ec_doctor.check_data_root(cfg))
            if not skip_api:
                with silenced_stdout():
                    results.append(ec_doctor.check_embedding_api(cfg))

    all_ok = all(r["ok"] for r in results)
    return text_result({"all_ok": all_ok, "checks": results})


# ---------------------------------------------------------------------------
# Registry consumed by dispatch.handle_tools_call
# ---------------------------------------------------------------------------
HANDLERS = {
    "search": tool_search,
    "list_mails": tool_list_mails,
    "read_mail": tool_read_mail,
    "read_meta": tool_read_meta,
    "read_attachment": tool_read_attachment,
    "stats": tool_stats,
    "convert": tool_convert,
    "index": tool_index,
    "ingest": tool_ingest,
    "doctor": tool_doctor,
}
