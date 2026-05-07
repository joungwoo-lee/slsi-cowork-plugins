"""Phase 2: read already-converted per-mail folders and index them.

Reads cfg.files_root/[Mail_ID]/{meta.json, body.md} and:
  - upserts metadata + body content into SQLite (FTS5 for keyword search)
  - if embeddings are enabled, calls the external embedding API and upserts
    the dense vector into the local Qdrant collection.

Does NOT touch the PST. Run this after convert.py, or stand-alone whenever
you need to rebuild the index (e.g. switching embedding model / dim).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Iterable, Iterator

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.config import Config, load_config  # type: ignore
    from scripts.embedding_client import EmbeddingClient  # type: ignore
    from scripts import storage  # type: ignore
else:
    from .config import Config, load_config
    from .embedding_client import EmbeddingClient
    from . import storage

log = logging.getLogger("email_connector.index")


def _iter_mail_dirs(cfg: Config, mail_ids: Iterable[str] | None = None) -> Iterator[Path]:
    if mail_ids:
        for mid in mail_ids:
            d = cfg.mail_dir(mid)
            if (d / "meta.json").exists() and (d / "body.md").exists():
                yield d
            else:
                log.warning("skipping %s: meta.json or body.md missing", mid)
        return
    if not cfg.files_root.exists():
        return
    for d in sorted(cfg.files_root.iterdir()):
        if d.is_dir() and (d / "meta.json").exists() and (d / "body.md").exists():
            yield d


def run_index(
    cfg: Config,
    *,
    skip_embedding: bool = False,
    mail_ids: Iterable[str] | None = None,
) -> int:
    """Index every mail folder under cfg.files_root. Returns number indexed."""
    cfg.ensure_dirs()

    embed_client: EmbeddingClient | None = None
    qdrant_client = None
    if not skip_embedding:
        embed_client = EmbeddingClient(cfg.embedding)
        qdrant_client = storage.open_qdrant(cfg)
        storage.ensure_collection(qdrant_client, cfg)

    indexed = 0
    with storage.sqlite_session(cfg) as conn:
        for mail_dir in _iter_mail_dirs(cfg, mail_ids):
            try:
                meta = json.loads((mail_dir / "meta.json").read_text(encoding="utf-8"))
                body = (mail_dir / "body.md").read_text(encoding="utf-8")
            except Exception as exc:
                log.warning("failed to read %s: %s", mail_dir.name, exc)
                continue

            mail_id = meta.get("mail_id") or mail_dir.name
            body_path = cfg.body_md_path(mail_id)

            has_vector = False
            if embed_client and qdrant_client:
                try:
                    [vector] = embed_client.embed([body[: cfg.ingest.max_body_chars]])
                    storage.upsert_vector(
                        qdrant_client,
                        cfg,
                        mail_id=mail_id,
                        vector=vector,
                        payload={
                            "subject": meta.get("subject", ""),
                            "sender": meta.get("sender", ""),
                            "received": meta.get("received", ""),
                            "body_path": str(body_path),
                        },
                    )
                    has_vector = True
                except Exception as exc:
                    log.warning("embedding upsert failed for %s: %s", mail_id, exc)

            storage.upsert_metadata(
                conn,
                mail_id=mail_id,
                subject=meta.get("subject", ""),
                sender=meta.get("sender", ""),
                recipients=meta.get("recipients", ""),
                received=meta.get("received", ""),
                folder_path=meta.get("folder_path", ""),
                body_path=str(body_path),
                content=body,
                has_vector=has_vector,
            )
            indexed += 1
            if indexed % 50 == 0:
                log.info("indexed %d messages...", indexed)
                conn.commit()
    log.info("index done. indexed=%d", indexed)
    return indexed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 2: index already-converted mail folders into SQLite + Qdrant.",
    )
    parser.add_argument("--env", default=None, help="Path to .env (default: <skill_root>/.env)")
    parser.add_argument(
        "--skip-embedding",
        action="store_true",
        help="Only update SQLite FTS5; do not call the embedding API or Qdrant.",
    )
    parser.add_argument(
        "--mail-id",
        action="append",
        default=None,
        help="Index only the given Mail_ID(s). May be repeated. Default: all.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = load_config(args.env)
    n = run_index(cfg, skip_embedding=args.skip_embedding, mail_ids=args.mail_id)
    print(json.dumps({"indexed": n, "db": str(cfg.db_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
