"""End-to-end pipeline: convert (Phase 1) → index (Phase 2).

Thin wrapper kept for backwards-compatible single-command usage. For phase-by-
phase control use scripts/convert.py and scripts/index.py directly.

INVOCATION: py -3.9 scripts\\ingest.py   (never bare python — see SKILL.md)
"""
from __future__ import annotations

import sys
if sys.version_info[:2] != (3, 9):
    raise SystemExit(
        "email-connector requires Python 3.9 (got "
        f"{sys.version_info.major}.{sys.version_info.minor} at {sys.executable}).\n"
        "Run with the launcher: py -3.9 scripts\\ingest.py"
    )

import argparse
import json
import logging
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.config import load_config  # type: ignore
    from scripts.convert import run_convert  # type: ignore
    from scripts.index import run_index  # type: ignore
else:
    from .config import load_config
    from .convert import run_convert
    from .index import run_index

log = logging.getLogger("email_connector.ingest")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="py -3.9 scripts\\ingest.py",
        description="Run convert + index in one go (Phase 1 then Phase 2). Must be run with Python 3.9.",
    )
    parser.add_argument("--pst", default=None, help="Path to .pst file (default: PST_PATH from .env)")
    parser.add_argument("--env", default=None, help="Path to .env (default: <skill_root>/.env)")
    parser.add_argument("--limit", type=int, default=None, help="Convert at most N messages")
    parser.add_argument(
        "--skip-embedding",
        action="store_true",
        help="Skip embedding API + Qdrant (only build SQLite FTS5 index).",
    )
    parser.add_argument(
        "--skip-convert",
        action="store_true",
        help="Skip Phase 1; reuse existing files under cfg.files_root.",
    )
    parser.add_argument(
        "--skip-index",
        action="store_true",
        help="Skip Phase 2; only convert PST to files.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = load_config(args.env)

    converted = 0
    indexed = 0
    if not args.skip_convert:
        pst = args.pst or cfg.pst_path
        if not pst:
            parser.error("--pst not provided and PST_PATH is empty in .env")
        converted = run_convert(pst, cfg, limit=args.limit)
    if not args.skip_index:
        indexed = run_index(cfg, skip_embedding=args.skip_embedding)

    print(
        json.dumps(
            {
                "converted": converted,
                "indexed": indexed,
                "files_root": str(cfg.files_root),
                "db": str(cfg.db_path),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
