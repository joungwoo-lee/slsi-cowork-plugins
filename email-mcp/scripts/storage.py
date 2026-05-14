"""SQLite (metadata + FTS5) and Qdrant (local) storage layer."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from .config import Config

SCHEMA = """
CREATE TABLE IF NOT EXISTS mail_metadata (
    mail_id      TEXT PRIMARY KEY,
    subject      TEXT,
    sender       TEXT,
    recipients   TEXT,
    received     TEXT,
    folder_path  TEXT,
    body_path    TEXT,
    has_vector   INTEGER DEFAULT 0,
    indexed_at   TEXT DEFAULT (datetime('now'))
);

CREATE VIRTUAL TABLE IF NOT EXISTS mail_fts USING fts5(
    mail_id UNINDEXED,
    subject,
    sender,
    content,
    tokenize='trigram'
);
"""


def open_sqlite(cfg: Config) -> sqlite3.Connection:
    cfg.ensure_dirs()
    conn = sqlite3.connect(cfg.db_path)
    conn.executescript(SCHEMA)
    _migrate_fts_tokenizer(conn)
    conn.commit()
    return conn


def _migrate_fts_tokenizer(conn: sqlite3.Connection) -> None:
    # Rebuild mail_fts with the trigram tokenizer so Korean substring queries
    # match (unicode61 splits only on whitespace/punctuation, leaving Korean
    # eojeol tokens un-matchable by their stem).
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='mail_fts'"
    ).fetchone()
    if not row or "trigram" in (row[0] or "").lower():
        return
    conn.execute("DROP TABLE mail_fts")
    conn.executescript(
        """
        CREATE VIRTUAL TABLE mail_fts USING fts5(
            mail_id UNINDEXED,
            subject,
            sender,
            content,
            tokenize='trigram'
        );
        """
    )
    rows = conn.execute(
        "SELECT mail_id, subject, sender, body_path FROM mail_metadata"
    ).fetchall()
    for mail_id, subject, sender, body_path in rows:
        content = ""
        if body_path:
            try:
                content = Path(body_path).read_text(encoding="utf-8", errors="replace")
            except Exception:
                content = ""
        conn.execute(
            "INSERT INTO mail_fts(mail_id, subject, sender, content) VALUES (?, ?, ?, ?)",
            (mail_id, subject or "", sender or "", content),
        )


@contextmanager
def sqlite_session(cfg: Config) -> Iterator[sqlite3.Connection]:
    conn = open_sqlite(cfg)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert_metadata(
    conn: sqlite3.Connection,
    *,
    mail_id: str,
    subject: str,
    sender: str,
    recipients: str,
    received: str,
    folder_path: str,
    body_path: str,
    content: str,
    has_vector: bool,
) -> None:
    conn.execute(
        """
        INSERT INTO mail_metadata
            (mail_id, subject, sender, recipients, received, folder_path, body_path, has_vector)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(mail_id) DO UPDATE SET
            subject=excluded.subject,
            sender=excluded.sender,
            recipients=excluded.recipients,
            received=excluded.received,
            folder_path=excluded.folder_path,
            body_path=excluded.body_path,
            has_vector=excluded.has_vector,
            indexed_at=datetime('now')
        """,
        (mail_id, subject, sender, recipients, received, folder_path, str(body_path), int(has_vector)),
    )
    conn.execute("DELETE FROM mail_fts WHERE mail_id = ?", (mail_id,))
    conn.execute(
        "INSERT INTO mail_fts (mail_id, subject, sender, content) VALUES (?, ?, ?, ?)",
        (mail_id, subject or "", sender or "", content or ""),
    )


def candidate_mail_ids(
    conn: sqlite3.Connection,
    *,
    sender_like: str | None = None,
    sender_not_like: str | None = None,
    sender_exact: str | None = None,
    received_from: str | None = None,
    received_to: str | None = None,
) -> list[str] | None:
    clauses: list[str] = []
    params: list[str] = []
    if sender_exact:
        clauses.append("sender = ?")
        params.append(sender_exact)
    if sender_like:
        clauses.append("LOWER(sender) LIKE ?")
        params.append(f"%{sender_like.lower()}%")
    if sender_not_like:
        clauses.append("LOWER(sender) NOT LIKE ?")
        params.append(f"%{sender_not_like.lower()}%")
    if received_from:
        clauses.append("received >= ?")
        params.append(received_from)
    if received_to:
        clauses.append("received <= ?")
        params.append(received_to)
    if not clauses:
        return None
    sql = "SELECT mail_id FROM mail_metadata WHERE " + " AND ".join(clauses)
    rows = conn.execute(sql, params).fetchall()
    return [row[0] for row in rows]


def fts_search(
    conn: sqlite3.Connection,
    query: str,
    limit: int,
    *,
    candidate_mail_ids: list[str] | None = None,
) -> list[dict]:
    """Return [{mail_id, score, snippet, subject, sender, received, body_path}, ...]."""
    sql = """
        SELECT m.mail_id, m.subject, m.sender, m.received, m.body_path,
               bm25(mail_fts) AS score,
               snippet(mail_fts, 3, '<<', '>>', ' … ', 12) AS snippet
        FROM mail_fts
        JOIN mail_metadata m ON m.mail_id = mail_fts.mail_id
    """
    params: list[object] = [query]
    where = ["mail_fts MATCH ?"]
    if candidate_mail_ids is not None:
        if not candidate_mail_ids:
            return []
        placeholders = ",".join("?" * len(candidate_mail_ids))
        where.append(f"m.mail_id IN ({placeholders})")
        params.extend(candidate_mail_ids)
    sql += " WHERE " + " AND ".join(where) + " ORDER BY score LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    cols = ["mail_id", "subject", "sender", "received", "body_path", "score", "snippet"]
    return [dict(zip(cols, row)) for row in rows]


def fetch_metadata(conn: sqlite3.Connection, mail_ids: list[str]) -> dict[str, dict]:
    if not mail_ids:
        return {}
    placeholders = ",".join("?" * len(mail_ids))
    rows = conn.execute(
        f"SELECT mail_id, subject, sender, received, body_path FROM mail_metadata WHERE mail_id IN ({placeholders})",
        mail_ids,
    ).fetchall()
    return {
        row[0]: {"mail_id": row[0], "subject": row[1], "sender": row[2], "received": row[3], "body_path": row[4]}
        for row in rows
    }


def open_qdrant(cfg: Config) -> QdrantClient:
    cfg.ensure_dirs()
    return QdrantClient(path=str(cfg.vector_db_path))


def ensure_collection(client: QdrantClient, cfg: Config) -> None:
    distance = getattr(qm.Distance, cfg.qdrant.distance.upper(), qm.Distance.COSINE)
    existing = {c.name for c in client.get_collections().collections}
    if cfg.qdrant.collection in existing:
        return
    client.create_collection(
        collection_name=cfg.qdrant.collection,
        vectors_config=qm.VectorParams(size=cfg.embedding.dim, distance=distance),
    )


def upsert_vector(
    client: QdrantClient,
    cfg: Config,
    *,
    mail_id: str,
    vector: list[float],
    payload: dict,
) -> None:
    client.upsert(
        collection_name=cfg.qdrant.collection,
        points=[
            qm.PointStruct(
                id=_qdrant_id(mail_id),
                vector=vector,
                payload={"mail_id": mail_id, **payload},
            )
        ],
    )


def vector_search(
    client: QdrantClient,
    cfg: Config,
    vector: list[float],
    limit: int,
    *,
    candidate_mail_ids: list[str] | None = None,
) -> list[dict]:
    # qdrant-client 1.7.0: client.search returns a list of ScoredPoint directly
    # (no .points wrapper). query_points() only exists from 1.10+.
    query_filter = None
    if candidate_mail_ids is not None:
        if not candidate_mail_ids:
            return []
        query_filter = qm.Filter(
            must=[qm.FieldCondition(key="mail_id", match=qm.MatchAny(any=candidate_mail_ids))]
        )
    response = client.search(
        collection_name=cfg.qdrant.collection,
        query_vector=vector,
        limit=limit,
        with_payload=True,
        query_filter=query_filter,
    )
    return [
        {
            "mail_id": h.payload.get("mail_id"),
            "score": float(h.score),
            "payload": h.payload,
        }
        for h in response
        if h.payload and h.payload.get("mail_id")
    ]


def _qdrant_id(mail_id: str) -> int:
    """Qdrant accepts int / UUID. Hash mail_id to a stable 64-bit int."""
    import hashlib
    # Use MD5 and take the first 8 bytes (64 bits) to convert to int.
    # Qdrant's integer IDs must be within 0 and 2^64-1 (unsigned).
    # Python's int is arbitrary precision, but for safety with Qdrant, 
    # we'll use 63 bits to avoid potential signed/unsigned issues in some backends.
    h = hashlib.md5(mail_id.encode("utf-8")).hexdigest()
    return int(h[:15], 16)
