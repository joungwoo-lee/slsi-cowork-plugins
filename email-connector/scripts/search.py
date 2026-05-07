"""Hybrid search: SQLite FTS5 (keyword) + Qdrant (semantic) with score fusion."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.config import Config, load_config  # type: ignore
    from scripts.embedding_client import EmbeddingClient  # type: ignore
    from scripts import storage  # type: ignore
else:
    from .config import Config, load_config
    from .embedding_client import EmbeddingClient
    from . import storage

log = logging.getLogger("email_connector.search")


def _normalize_keyword_scores(rows: list[dict]) -> dict[str, float]:
    """bm25 returns lower-is-better. Invert + min-max normalize to [0,1]."""
    if not rows:
        return {}
    inverted = [(r["mail_id"], -float(r["score"])) for r in rows]
    values = [v for _, v in inverted]
    lo, hi = min(values), max(values)
    spread = hi - lo or 1.0
    return {mid: (v - lo) / spread for mid, v in inverted}


def _normalize_semantic_scores(rows: list[dict]) -> dict[str, float]:
    """Qdrant cosine similarity is already in [-1,1]; clamp+rescale to [0,1]."""
    return {r["mail_id"]: max(0.0, min(1.0, (float(r["score"]) + 1.0) / 2.0)) for r in rows}


def hybrid_search(
    cfg: Config,
    query: str,
    *,
    top: int = 10,
    mode: str = "hybrid",
) -> list[dict]:
    keyword_rows: list[dict] = []
    semantic_rows: list[dict] = []
    snippets: dict[str, str] = {}

    with storage.sqlite_session(cfg) as conn:
        if mode in ("hybrid", "keyword"):
            keyword_rows = storage.fts_search(conn, query, top * 4)
            snippets = {r["mail_id"]: r.get("snippet", "") for r in keyword_rows}

        if mode in ("hybrid", "semantic"):
            client = EmbeddingClient(cfg.embedding)
            [vector] = client.embed([query])
            qdrant = storage.open_qdrant(cfg)
            storage.ensure_collection(qdrant, cfg)
            semantic_rows = storage.vector_search(qdrant, cfg, vector, top * 4)

        kw_scores = _normalize_keyword_scores(keyword_rows)
        sem_scores = _normalize_semantic_scores(semantic_rows)

        alpha = cfg.search.hybrid_alpha
        if mode == "keyword":
            alpha = 1.0
        elif mode == "semantic":
            alpha = 0.0

        all_ids = set(kw_scores) | set(sem_scores)
        meta = storage.fetch_metadata(conn, list(all_ids))

    results: list[dict] = []
    for mid in all_ids:
        kw = kw_scores.get(mid, 0.0)
        sem = sem_scores.get(mid, 0.0)
        combined = alpha * kw + (1 - alpha) * sem
        m = meta.get(mid, {})
        results.append(
            {
                "mail_id": mid,
                "subject": m.get("subject", ""),
                "sender": m.get("sender", ""),
                "received": m.get("received", ""),
                "body_path": m.get("body_path", ""),
                "score": round(combined, 6),
                "score_keyword": round(kw, 6),
                "score_semantic": round(sem, 6),
                "snippet": snippets.get(mid, ""),
            }
        )

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top]


def main() -> None:
    parser = argparse.ArgumentParser(description="Hybrid search over an ingested PST index.")
    parser.add_argument("--query", required=True)
    parser.add_argument("--env", default=None, help="Path to .env (default: <skill_root>/.env)")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--mode", choices=("hybrid", "keyword", "semantic"), default="hybrid")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = load_config(args.env)
    results = hybrid_search(cfg, args.query, top=args.top, mode=args.mode)
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
