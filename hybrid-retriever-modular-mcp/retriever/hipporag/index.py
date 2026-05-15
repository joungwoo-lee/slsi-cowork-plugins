"""HippoRAG indexing orchestrator.

Two entry points:

- ``index_dataset(cfg, dataset_id)`` — full re-index of every chunk in a
  dataset. Idempotent: re-running with an unchanged corpus is a no-op
  beyond cache hits. Use after a fresh bulk upload, or to backfill an
  existing dataset that pre-dates HippoRAG.

- ``index_document(cfg, dataset_id, document_id)`` — incremental: only
  re-extracts triples for one document's chunks, then rebuilds synonyms
  + marks the graph dirty so the next search/rebuild picks up the
  change. Intended to be called automatically from ``upload_document``.
"""
from __future__ import annotations

import logging
import sqlite3
import time

from ..config import Config
from ..graph import mark_dirty, set_state
from . import entities as ent_mod
from .openie import OpenIEExtractor
from .synonyms import rebuild_synonyms

log = logging.getLogger(__name__)


def _require_llm(cfg: Config) -> None:
    if not cfg.llm or not cfg.llm.is_configured:
        raise RuntimeError(
            "HippoRAG requires an LLM endpoint. Set LLM_API_URL and LLM_MODEL "
            "in .env, then restart the MCP server."
        )


def _require_embedding(cfg: Config) -> None:
    if not cfg.embedding or not cfg.embedding.is_configured:
        raise RuntimeError(
            "HippoRAG requires an embedding endpoint for entity vectors. "
            "Set EMBEDDING_API_URL and EMBEDDING_DIM in .env."
        )


def _fetch_chunks(
    conn: sqlite3.Connection,
    *,
    dataset_id: str | None = None,
    document_id: str | None = None,
) -> list[tuple[str, str, str, str]]:
    """Return ``[(chunk_id, content, document_id, dataset_id), ...]`` ordered."""
    if document_id:
        rows = conn.execute(
            "SELECT chunk_id, content, document_id, dataset_id FROM chunks "
            "WHERE document_id = ? ORDER BY position",
            (document_id,),
        ).fetchall()
    elif dataset_id:
        rows = conn.execute(
            "SELECT chunk_id, content, document_id, dataset_id FROM chunks "
            "WHERE dataset_id = ? ORDER BY document_id, position",
            (dataset_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT chunk_id, content, document_id, dataset_id FROM chunks "
            "ORDER BY dataset_id, document_id, position"
        ).fetchall()
    return [(r[0], r[1] or "", r[2], r[3]) for r in rows]


def index_chunks(
    cfg: Config,
    sqlite_conn: sqlite3.Connection,
    chunks: list[tuple[str, str, str, str]],
    *,
    max_workers: int = 4,
) -> dict:
    """Run OpenIE + entity upsert for an explicit chunk list.

    Callers usually want ``index_dataset`` or ``index_document`` instead;
    this is the internal worker shared by both.
    """
    _require_llm(cfg)
    if not chunks:
        return {"chunks_processed": 0, "triples_written": 0, "entities_embedded": 0}

    started = time.time()
    extractor = OpenIEExtractor(cfg.llm, cfg.hipporag)

    chunk_ids = [c[0] for c in chunks]
    # Wipe old mentions/triples for these chunks so re-indexing doesn't
    # double-count an entity. Triples are dropped explicitly (we re-derive
    # them) but the cache table is left alone — same chunk hash + model
    # will hit the cache on the next call.
    ent_mod.clear_chunk_mentions(sqlite_conn, chunk_ids)
    ent_mod.clear_chunk_triples(sqlite_conn, chunk_ids)
    sqlite_conn.commit()

    triples_map = extractor.extract_chunks(
        sqlite_conn,
        ((cid, content) for cid, content, _did, _sid in chunks),
        max_workers=max_workers,
    )

    written = 0
    for chunk_id, content, document_id, dataset_id in chunks:
        triples = triples_map.get(chunk_id, [])
        if not triples:
            continue
        written += ent_mod.persist_triples(
            sqlite_conn,
            chunk_id=chunk_id,
            document_id=document_id,
            dataset_id=dataset_id,
            triples=triples,
        )
    sqlite_conn.commit()

    embedded = 0
    if cfg.embedding and cfg.embedding.is_configured:
        embedded = ent_mod.embed_pending_entities(sqlite_conn, cfg.embedding)

    mark_dirty(sqlite_conn)
    set_state(sqlite_conn, "last_index_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    sqlite_conn.commit()

    return {
        "chunks_processed": len(chunks),
        "triples_written": written,
        "entities_embedded": embedded,
        "elapsed_sec": round(time.time() - started, 2),
    }


def index_dataset(
    cfg: Config,
    sqlite_conn: sqlite3.Connection,
    dataset_id: str,
    *,
    rebuild_synonyms_after: bool = True,
    max_workers: int = 4,
) -> dict:
    _require_llm(cfg)
    _require_embedding(cfg)
    chunks = _fetch_chunks(sqlite_conn, dataset_id=dataset_id)
    result = index_chunks(cfg, sqlite_conn, chunks, max_workers=max_workers)
    if rebuild_synonyms_after and result["chunks_processed"] > 0:
        syn = rebuild_synonyms(sqlite_conn, cfg.hipporag)
        sqlite_conn.commit()
        result["synonyms"] = syn
    return result


def index_document(
    cfg: Config,
    sqlite_conn: sqlite3.Connection,
    document_id: str,
    *,
    rebuild_synonyms_after: bool = False,
    max_workers: int = 4,
) -> dict:
    """Incremental hook for ``upload_document``.

    ``rebuild_synonyms_after`` defaults False because synonyms are an
    all-pairs operation; running per-document during a bulk
    ``upload_directory`` would be wasteful. Schedule a synonym refresh
    explicitly at the end of a batch via ``hipporag_refresh_synonyms``.
    """
    _require_llm(cfg)
    chunks = _fetch_chunks(sqlite_conn, document_id=document_id)
    result = index_chunks(cfg, sqlite_conn, chunks, max_workers=max_workers)
    if rebuild_synonyms_after and result["chunks_processed"] > 0 and cfg.embedding and cfg.embedding.is_configured:
        syn = rebuild_synonyms(sqlite_conn, cfg.hipporag)
        sqlite_conn.commit()
        result["synonyms"] = syn
    return result
