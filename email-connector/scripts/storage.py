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
    tokenize='unicode61'
);
"""


def open_sqlite(cfg: Config) -> sqlite3.Connection:
    cfg.ensure_dirs()
    conn = sqlite3.connect(cfg.db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


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


def fts_search(conn: sqlite3.Connection, query: str, limit: int) -> list[dict]:
    """Return [{mail_id, score, snippet, subject, sender, received, body_path}, ...]."""
    sql = """
        SELECT m.mail_id, m.subject, m.sender, m.received, m.body_path,
               bm25(mail_fts) AS score,
               snippet(mail_fts, 3, '<<', '>>', ' … ', 12) AS snippet
        FROM mail_fts
        JOIN mail_metadata m ON m.mail_id = mail_fts.mail_id
        WHERE mail_fts MATCH ?
        ORDER BY score
        LIMIT ?
    """
    rows = conn.execute(sql, (query, limit)).fetchall()
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
    client: QdrantClient, cfg: Config, vector: list[float], limit: int
) -> list[dict]:
    hits = client.search(
        collection_name=cfg.qdrant.collection,
        query_vector=vector,
        limit=limit,
        with_payload=True,
    )
    return [
        {
            "mail_id": h.payload.get("mail_id"),
            "score": float(h.score),
            "payload": h.payload,
        }
        for h in hits
        if h.payload and h.payload.get("mail_id")
    ]


def _qdrant_id(mail_id: str) -> int:
    """Qdrant accepts int / UUID. Hash mail_id to a stable 63-bit int."""
    return int(mail_id[:15], 16)
