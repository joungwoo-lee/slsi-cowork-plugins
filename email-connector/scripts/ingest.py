"""ETL: PST → unified markdown → SQLite FTS5 + Qdrant."""
from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

# Allow running both as `python -m scripts.ingest` and `python scripts/ingest.py`.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.config import Config, load_config  # type: ignore
    from scripts.embedding_client import EmbeddingClient  # type: ignore
    from scripts.markdown_converter import (  # type: ignore
        attachment_to_markdown,
        body_to_markdown,
        build_unified_markdown,
    )
    from scripts.pst_extractor import MailMessage, iter_messages  # type: ignore
    from scripts import storage  # type: ignore
else:
    from .config import Config, load_config
    from .embedding_client import EmbeddingClient
    from .markdown_converter import (
        attachment_to_markdown,
        body_to_markdown,
        build_unified_markdown,
    )
    from .pst_extractor import MailMessage, iter_messages
    from . import storage

log = logging.getLogger("email_connector.ingest")

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


def _process_message(cfg: Config, msg: MailMessage) -> tuple[str, Path] | None:
    """Write per-mail folder + body.md. Returns (unified_text, body_md_path) or None on error."""
    mail_dir = cfg.mail_dir(msg.mail_id)
    mail_dir.mkdir(parents=True, exist_ok=True)
    body_md = body_to_markdown(msg.body_html, msg.body_plain, cfg.ingest.max_body_chars)

    attachment_sections: list[tuple[str, str]] = []
    for att in msg.attachments:
        if not att.data:
            continue
        _save_attachment(cfg.attachments_dir(msg.mail_id), att.filename, att.data)
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
    body_path = cfg.body_md_path(msg.mail_id)
    body_path.write_text(unified, encoding="utf-8")
    return unified, body_path


def run_ingest(
    pst_path: str,
    cfg: Config,
    *,
    limit: int | None = None,
    skip_embedding: bool = False,
) -> None:
    cfg.ensure_dirs()
    embed_client: EmbeddingClient | None = None
    qdrant_client = None
    if not skip_embedding:
        embed_client = EmbeddingClient(cfg.embedding)
        qdrant_client = storage.open_qdrant(cfg)
        storage.ensure_collection(qdrant_client, cfg)

    processed = 0
    with storage.sqlite_session(cfg) as conn:
        for msg in iter_messages(pst_path):
            try:
                result = _process_message(cfg, msg)
            except Exception as exc:
                log.warning("failed to process mail %s: %s", msg.mail_id, exc)
                continue
            if result is None:
                continue
            unified_text, body_path = result

            has_vector = False
            if embed_client and qdrant_client:
                try:
                    [vector] = embed_client.embed([unified_text[: cfg.ingest.max_body_chars]])
                    storage.upsert_vector(
                        qdrant_client,
                        cfg,
                        mail_id=msg.mail_id,
                        vector=vector,
                        payload={
                            "subject": msg.subject,
                            "sender": msg.sender,
                            "received": msg.received,
                            "body_path": str(body_path),
                        },
                    )
                    has_vector = True
                except Exception as exc:
                    log.warning("embedding upsert failed for %s: %s", msg.mail_id, exc)

            storage.upsert_metadata(
                conn,
                mail_id=msg.mail_id,
                subject=msg.subject,
                sender=msg.sender,
                recipients=msg.recipients,
                received=msg.received,
                folder_path=msg.folder_path,
                body_path=str(body_path),
                content=unified_text,
                has_vector=has_vector,
            )
            processed += 1
            if processed % 50 == 0:
                log.info("ingested %d messages...", processed)
                conn.commit()
            if limit is not None and processed >= limit:
                break
    log.info("done. ingested=%d", processed)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest a PST into the hybrid index.")
    parser.add_argument("--pst", required=True, help="Path to .pst file")
    parser.add_argument("--config", required=True, help="Path to config.json")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N messages")
    parser.add_argument(
        "--skip-embedding",
        action="store_true",
        help="Skip embedding API + Qdrant (only build SQLite FTS5 index)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = load_config(args.config)
    run_ingest(args.pst, cfg, limit=args.limit, skip_embedding=args.skip_embedding)


if __name__ == "__main__":
    main()
