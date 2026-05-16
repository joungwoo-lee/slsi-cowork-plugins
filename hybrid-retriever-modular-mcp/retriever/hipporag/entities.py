"""Entity canonicalisation, persistence, and embedding.

Canonicalisation is deliberately conservative: NFKC normalise, lowercase
ASCII letters (CJK passes through), collapse whitespace, strip surrounding
quotation marks and punctuation. The intent is to merge "Samsung" /
"  samsung " / "Samsung." into one entity without aggressively merging
"Samsung Electronics" with "Samsung" — that's what the SYNONYM edges are
for, downstream.
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
import unicodedata
from dataclasses import dataclass

from ..config import EmbeddingConfig
from ..embedding_client import EmbeddingClient
from ..graph import pack_vector
from .openie import Triple

log = logging.getLogger(__name__)

_TRIM_CHARS = " \t\r\n\"'`«»“”‘’()[]{}<>.,;:!?"


def canonicalize(surface: str) -> str:
    if not surface:
        return ""
    text = unicodedata.normalize("NFKC", surface).strip(_TRIM_CHARS)
    text = " ".join(text.split())
    return text.lower()


def entity_id_for(canonical: str) -> str:
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class EntityRef:
    entity_id: str
    canonical: str
    surface: str

    @classmethod
    def from_surface(cls, surface: str) -> "EntityRef | None":
        canon = canonicalize(surface)
        if not canon:
            return None
        return cls(entity_id=entity_id_for(canon), canonical=canon, surface=surface)


def upsert_entity(conn: sqlite3.Connection, ref: EntityRef, *, entity_type: str = "") -> None:
    conn.execute(
        "INSERT INTO entities(entity_id, canonical, surface, type, mention_count) "
        "VALUES(?, ?, ?, ?, 0) ON CONFLICT(entity_id) DO NOTHING",
        (ref.entity_id, ref.canonical, ref.surface, entity_type),
    )


def record_mention(conn: sqlite3.Connection, chunk_id: str, entity_id: str) -> None:
    conn.execute(
        "INSERT INTO chunk_mentions(chunk_id, entity_id, count) VALUES(?, ?, 1) "
        "ON CONFLICT(chunk_id, entity_id) DO UPDATE SET count = count + 1",
        (chunk_id, entity_id),
    )
    conn.execute(
        "UPDATE entities SET mention_count = mention_count + 1 WHERE entity_id = ?",
        (entity_id,),
    )


def clear_chunk_mentions(conn: sqlite3.Connection, chunk_ids: list[str]) -> None:
    """Used by incremental re-index: drop a chunk's old mentions before re-adding.

    Also decrements ``entities.mention_count`` so the counter stays honest.
    """
    if not chunk_ids:
        return
    placeholders = ",".join("?" * len(chunk_ids))
    rows = conn.execute(
        f"SELECT entity_id, count FROM chunk_mentions WHERE chunk_id IN ({placeholders})",
        chunk_ids,
    ).fetchall()
    for entity_id, count in rows:
        conn.execute(
            "UPDATE entities SET mention_count = MAX(0, mention_count - ?) WHERE entity_id = ?",
            (int(count or 0), entity_id),
        )
    conn.execute(f"DELETE FROM chunk_mentions WHERE chunk_id IN ({placeholders})", chunk_ids)


def clear_chunk_triples(conn: sqlite3.Connection, chunk_ids: list[str]) -> None:
    if not chunk_ids:
        return
    placeholders = ",".join("?" * len(chunk_ids))
    conn.execute(f"DELETE FROM triples WHERE chunk_id IN ({placeholders})", chunk_ids)


def triple_id_for(chunk_id: str, subj_id: str, pred: str, obj_id: str) -> str:
    h = hashlib.sha1()
    h.update(chunk_id.encode("utf-8"))
    h.update(b"|")
    h.update(subj_id.encode("utf-8"))
    h.update(b"|")
    h.update(pred.encode("utf-8"))
    h.update(b"|")
    h.update(obj_id.encode("utf-8"))
    return h.hexdigest()[:20]


def persist_triples(
    conn: sqlite3.Connection,
    *,
    chunk_id: str,
    document_id: str,
    dataset_id: str,
    triples: list[Triple],
    confidence: float = 1.0,
) -> int:
    """Upsert entities + relation triples + chunk_mentions for one chunk.

    Returns the number of triples written (after deduplication and canonical
    collapse — e.g. two surface forms mapping to the same canonical entity
    can yield a single triple).
    """
    written = 0
    seen: set[str] = set()
    for t in triples:
        subj = EntityRef.from_surface(t.subject)
        obj = EntityRef.from_surface(t.object)
        if subj is None or obj is None:
            continue
        upsert_entity(conn, subj)
        upsert_entity(conn, obj)
        record_mention(conn, chunk_id, subj.entity_id)
        if obj.entity_id != subj.entity_id:
            record_mention(conn, chunk_id, obj.entity_id)
        tid = triple_id_for(chunk_id, subj.entity_id, t.predicate, obj.entity_id)
        if tid in seen:
            continue
        seen.add(tid)
        conn.execute(
            "INSERT INTO triples(triple_id, chunk_id, document_id, dataset_id, "
            "subj_id, pred, obj_id, confidence) VALUES(?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(triple_id) DO UPDATE SET confidence = excluded.confidence",
            (
                tid,
                chunk_id,
                document_id,
                dataset_id,
                subj.entity_id,
                t.predicate,
                obj.entity_id,
                float(confidence),
            ),
        )
        written += 1
    return written


def entities_missing_embeddings(conn: sqlite3.Connection, model: str) -> list[tuple[str, str]]:
    """Return ``[(entity_id, canonical), ...]`` for entities whose embedding
    is absent or was produced by a different model."""
    rows = conn.execute(
        """
        SELECT e.entity_id, e.canonical
        FROM entities e
        LEFT JOIN entity_embeddings emb ON emb.entity_id = e.entity_id
        WHERE emb.entity_id IS NULL OR emb.model != ?
        """,
        (model,),
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def embed_pending_entities(
    conn: sqlite3.Connection,
    embedding_cfg: EmbeddingConfig,
    *,
    batch_size: int | None = None,
) -> int:
    """Embed entities whose canonical text has no fresh embedding row.

    Returns the number of entities embedded. The embedding model name is
    stored alongside the BLOB so a model swap (text-embedding-3-small ->
    -large) triggers a re-embed of every entity on the next call.
    """
    if not embedding_cfg or not embedding_cfg.is_configured:
        log.info("embedding endpoint not configured — skipping entity embeddings")
        return 0

    client = EmbeddingClient(embedding_cfg)
    pending = entities_missing_embeddings(conn, embedding_cfg.model)
    if not pending:
        return 0

    bsz = max(1, int(batch_size or embedding_cfg.batch_size))
    n = 0
    for start in range(0, len(pending), bsz):
        batch = pending[start : start + bsz]
        texts = [canon for _eid, canon in batch]
        vectors = client.embed(texts)
        for (eid, _canon), vec in zip(batch, vectors):
            conn.execute(
                "INSERT INTO entity_embeddings(entity_id, model, dim, vector) "
                "VALUES(?, ?, ?, ?) ON CONFLICT(entity_id) DO UPDATE SET "
                "model = excluded.model, dim = excluded.dim, vector = excluded.vector, "
                "updated_at = datetime('now')",
                (eid, embedding_cfg.model, embedding_cfg.dim, pack_vector(vec)),
            )
            n += 1
        conn.commit()
    return n


def _fact_text(subj: str, pred: str, obj: str) -> str:
    return f"({subj}, {pred}, {obj})"


def facts_missing_embeddings(conn: sqlite3.Connection, model: str) -> list[tuple[str, str]]:
    rows = conn.execute(
        """
        SELECT t.triple_id, s.canonical, t.pred, o.canonical
        FROM triples t
        JOIN entities s ON s.entity_id = t.subj_id
        JOIN entities o ON o.entity_id = t.obj_id
        LEFT JOIN fact_embeddings emb ON emb.triple_id = t.triple_id
        WHERE emb.triple_id IS NULL OR emb.model != ?
        """,
        (model,),
    ).fetchall()
    return [(triple_id, _fact_text(subj, pred, obj)) for triple_id, subj, pred, obj in rows]


def embed_pending_facts(
    conn: sqlite3.Connection,
    embedding_cfg: EmbeddingConfig,
    *,
    batch_size: int | None = None,
) -> int:
    """Embed OpenIE triples for HippoRAG2 fact retrieval."""
    if not embedding_cfg or not embedding_cfg.is_configured:
        log.info("embedding endpoint not configured — skipping fact embeddings")
        return 0

    client = EmbeddingClient(embedding_cfg)
    pending = facts_missing_embeddings(conn, embedding_cfg.model)
    if not pending:
        return 0

    bsz = max(1, int(batch_size or embedding_cfg.batch_size))
    n = 0
    for start in range(0, len(pending), bsz):
        batch = pending[start : start + bsz]
        vectors = client.embed([text for _tid, text in batch])
        for (triple_id, _text), vec in zip(batch, vectors):
            conn.execute(
                "INSERT INTO fact_embeddings(triple_id, model, dim, vector) "
                "VALUES(?, ?, ?, ?) ON CONFLICT(triple_id) DO UPDATE SET "
                "model = excluded.model, dim = excluded.dim, vector = excluded.vector, "
                "updated_at = datetime('now')",
                (triple_id, embedding_cfg.model, embedding_cfg.dim, pack_vector(vec)),
            )
            n += 1
        conn.commit()
    return n
