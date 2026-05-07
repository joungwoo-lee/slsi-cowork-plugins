"""Phase 1: PST → unified markdown body + original-extension attachments + meta.json.

This phase does NOT touch SQLite or Qdrant. It only writes files to disk so that
phase 2 (index.py) can run independently — useful for re-indexing without
re-decoding the PST, or for changing embedding model / dim later.

Per-mail layout written under cfg.files_root:
    [Mail_ID]/
        body.md         # mail body markdown (with attachment text appended)
        meta.json       # subject, sender, recipients, received, folder_path, mail_id
        attachments/
            <original filename with original extension>
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.config import Config, load_config  # type: ignore
    from scripts.markdown_converter import (  # type: ignore
        attachment_to_markdown,
        body_to_markdown,
        build_unified_markdown,
    )
    from scripts.pst_extractor import MailMessage, iter_messages  # type: ignore
else:
    from .config import Config, load_config
    from .markdown_converter import (
        attachment_to_markdown,
        body_to_markdown,
        build_unified_markdown,
    )
    from .pst_extractor import MailMessage, iter_messages

log = logging.getLogger("email_connector.convert")

_INVALID_FS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _safe_filename(name: str) -> str:
    cleaned = _INVALID_FS.sub("_", name).strip().strip(".")
    return cleaned[:200] or "attachment"


def _save_attachment(target_dir: Path, filename: str, data: bytes) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    safe = _safe_filename(filename)
    path = target_dir / safe
    counter = 1
    while path.exists():
        stem, suffix = Path(safe).stem, Path(safe).suffix
        path = target_dir / f"{stem}_{counter}{suffix}"
        counter += 1
    path.write_bytes(data)
    return path


def _write_message(cfg: Config, msg: MailMessage) -> Path | None:
    """Write body.md / meta.json / attachments/ for one message. Returns mail dir."""
    mail_dir = cfg.mail_dir(msg.mail_id)
    mail_dir.mkdir(parents=True, exist_ok=True)
    att_dir = cfg.attachments_dir(msg.mail_id)
    if att_dir.exists():
        shutil.rmtree(att_dir)

    body_md = body_to_markdown(msg.body_html, msg.body_plain, cfg.ingest.max_body_chars)

    attachment_sections: list[tuple[str, str]] = []
    for att in msg.attachments:
        if not att.data:
            continue
        _save_attachment(att_dir, att.filename, att.data)
        md = attachment_to_markdown(att.filename, att.data, cfg.ingest.max_attachment_chars)
        if md:
            attachment_sections.append((att.filename, md))

    unified = build_unified_markdown(
        subject=msg.subject,
        sender=msg.sender,
        received=msg.received,
        folder_path=msg.folder_path,
        body_md=body_md,
        attachment_sections=attachment_sections,
    )
    cfg.body_md_path(msg.mail_id).write_text(unified, encoding="utf-8")
    (mail_dir / "meta.json").write_text(
        json.dumps(
            {
                "mail_id": msg.mail_id,
                "subject": msg.subject,
                "sender": msg.sender,
                "recipients": msg.recipients,
                "received": msg.received,
                "folder_path": msg.folder_path,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return mail_dir


def run_convert(pst_path: str, cfg: Config, *, limit: int | None = None) -> int:
    """Decode PST and write per-mail folders. Returns count of converted messages."""
    cfg.ensure_dirs()
    converted = 0
    for msg in iter_messages(pst_path):
        try:
            _write_message(cfg, msg)
            converted += 1
        except Exception as exc:
            log.warning("failed to convert mail %s: %s", msg.mail_id, exc)
            continue
        if converted % 50 == 0:
            log.info("converted %d messages...", converted)
        if limit is not None and converted >= limit:
            break
    log.info("convert done. converted=%d", converted)
    return converted


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 1: convert a PST into per-mail markdown + attachments. No indexing.",
    )
    parser.add_argument("--pst", default=None, help="Path to .pst file (default: PST_PATH from .env)")
    parser.add_argument("--env", default=None, help="Path to .env (default: <skill_root>/.env)")
    parser.add_argument("--limit", type=int, default=None, help="Convert at most N messages")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = load_config(args.env)
    pst = args.pst or cfg.pst_path
    if not pst:
        parser.error("--pst not provided and PST_PATH is empty in .env")
    n = run_convert(pst, cfg, limit=args.limit)
    print(json.dumps({"converted": n, "files_root": str(cfg.files_root)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
