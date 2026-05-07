"""End-to-end pipeline: convert (Phase 1) → index (Phase 2).

Thin wrapper kept for backwards-compatible single-command usage. For phase-by-
phase control use scripts/convert.py and scripts/index.py directly.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
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
        description="Run convert + index in one go (Phase 1 then Phase 2).",
    )
    parser.add_argument("--pst", required=True, help="Path to .pst file")
    parser.add_argument("--config", required=True, help="Path to config.json")
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
    cfg = load_config(args.config)

    converted = 0
    indexed = 0
    if not args.skip_convert:
        converted = run_convert(args.pst, cfg, limit=args.limit)
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
