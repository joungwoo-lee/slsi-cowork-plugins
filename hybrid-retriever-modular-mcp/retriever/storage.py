"""SQLite FTS5 + optional local Qdrant storage for documents and chunks.

FTS uses the plain `unicode61` tokenizer but text is pre-tokenized into Korean
morphemes (kiwipiepy) on both the index and query side. See `morph.py`.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from contextlib import contextmanager
from typing import Iterator

from .config import Config
from . import morph

# Bump when the FTS5 build strategy changes so existing DBs are rebuilt on
# the next open. 0 = legacy unicode61 (no morph), 1 = trigram, 2 = unicode61
# fed by kiwipiepy morphemes (current).
INDEX_SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
    dataset_id  TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    dataset_id  TEXT NOT NULL,
    name        TEXT NOT NULL,
    source_path TEXT NOT NULL,
    content_path TEXT NOT NULL,
    size_bytes  INTEGER DEFAULT 0,
    chunk_count INTEGER DEFAULT 0,
    has_vector  INTEGER DEFAULT 0,
    metadata_json TEXT DEFAULT '{}',
    created_at  TEXT DEFAULT (datetime('now')),
    FOREIGN KEY(dataset_id) REFERENCES datasets(dataset_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id    TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    dataset_id  TEXT NOT NULL,
    position    INTEGER NOT NULL,
    content     TEXT NOT NULL,
    original_content TEXT DEFAULT '',
    parent_content TEXT DEFAULT '',
    parent_id   INTEGER DEFAULT 0,
    child_id    INTEGER DEFAULT 0,
    is_hierarchical INTEGER DEFAULT 0,
    is_contextual INTEGER DEFAULT 0,
    metadata_json TEXT DEFAULT '{}',
    has_vector  INTEGER DEFAULT 0,
    FOREIGN KEY(document_id) REFERENCES documents(document_id) ON DELETE CASCADE
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
    chunk_id UNINDEXED,
    document_id UNINDEXED,
    dataset_id UNINDEXED,
    document_name,
    content,
    tokenize='unicode61'
);
"""


def open_sqlite(cfg: Config) -> sqlite3.Connection:
    cfg.ensure_dirs()
    conn = sqlite3.connect(cfg.db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(documents)").fetchall()}
    if "metadata_json" not in existing:
        conn.execute("ALTER TABLE documents ADD COLUMN metadata_json TEXT DEFAULT '{}'")
    existing = {row[1] for row in conn.execute("PRAGMA table_info(chunks)").fetchall()}
    for name, ddl in {
        "original_content": "TEXT DEFAULT ''",
        "parent_content": "TEXT DEFAULT ''",
        "parent_id": "INTEGER DEFAULT 0",
        "child_id": "INTEGER DEFAULT 0",
        "is_hierarchical": "INTEGER DEFAULT 0",
        "is_contextual": "INTEGER DEFAULT 0",
        "metadata_json": "TEXT DEFAULT '{}'",
    }.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE chunks ADD COLUMN {name} {ddl}")
    _migrate_fts_tokenizer(conn)


def _migrate_fts_tokenizer(conn: sqlite3.Connection) -> None:
    # Rebuild chunk_fts so it stores kiwipiepy-tokenized Korean morphemes
    # under the plain unicode61 tokenizer. This lets queries like "메일"
    # (2 chars) or "보고서" still match eojeol forms like "메일을" /
    # "보고서를" via morpheme-level identity.
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current >= INDEX_SCHEMA_VERSION:
        return
    conn.execute("DROP TABLE IF EXISTS chunk_fts")
    conn.executescript(
        """
        CREATE VIRTUAL TABLE chunk_fts USING fts5(
            chunk_id UNINDEXED,
            document_id UNINDEXED,
            dataset_id UNINDEXED,
            document_name,
            content,
            tokenize='unicode61'
        );
        """
    )
    rows = conn.execute(
        """
        SELECT c.chunk_id, c.document_id, c.dataset_id, d.name, c.content
        FROM chunks c JOIN documents d ON d.document_id = c.document_id
        """
    ).fetchall()
    for chunk_id, document_id, dataset_id, name, content in rows:
        conn.execute(
            "INSERT INTO chunk_fts(chunk_id, document_id, dataset_id, document_name, content) VALUES (?, ?, ?, ?, ?)",
            (
                chunk_id,
                document_id,
                dataset_id,
                morph.tokenize_for_index(name or ""),
                morph.tokenize_for_index(content or ""),
            ),
        )
    conn.execute(f"PRAGMA user_version = {INDEX_SCHEMA_VERSION}")


@contextmanager
def sqlite_session(cfg: Config) -> Iterator[sqlite3.Connection]:
    conn = open_sqlite(cfg)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def slug(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in value.strip())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned or "dataset"


def ensure_dataset(conn: sqlite3.Connection, dataset_id: str, name: str | None = None, description: str = "") -> None:
    conn.execute(
        "INSERT OR IGNORE INTO datasets(dataset_id, name, description) VALUES (?, ?, ?)",
        (dataset_id, name or dataset_id, description or ""),
    )


def upsert_document(
    conn: sqlite3.Connection,
    *,
    dataset_id: str,
    document_id: str,
    name: str,
    source_path: str,
    content_path: str,
    size_bytes: int,
    chunks: list[dict],
    has_vector: bool = False,
    metadata: dict | None = None,
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Delete existing chunks
    conn.execute("DELETE FROM chunk_fts WHERE chunk_id IN (SELECT chunk_id FROM chunks WHERE document_id = ?)", [document_id])
    conn.execute("DELETE FROM chunks WHERE document_id = ?", [document_id])

    metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
    conn.execute(
        """
        INSERT INTO documents (document_id, dataset_id, name, source_path, content_path, size_bytes, has_vector, created_at, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(document_id) DO UPDATE SET
            dataset_id=excluded.dataset_id,
            name=excluded.name,
            source_path=excluded.source_path,
            content_path=excluded.content_path,
            size_bytes=excluded.size_bytes,
            has_vector=excluded.has_vector,
            created_at=excluded.created_at,
            metadata_json=excluded.metadata_json
        """,
        [document_id, dataset_id, name, source_path, content_path, size_bytes, int(has_vector), now, metadata_json],
    )
    for pos, record in enumerate(chunks):
        content = record.get("child_content", "")
        chunk_id = f"{document_id}:{pos}"
        conn.execute(
            """
            INSERT INTO chunks(
                chunk_id, document_id, dataset_id, position, content, original_content,
                parent_content, parent_id, child_id, is_hierarchical, is_contextual,
                metadata_json, has_vector
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chunk_id,
                document_id,
                dataset_id,
                pos,
                content,
                record.get("original_child_content", content),
                record.get("parent_content", content),
                int(record.get("parent_id", 0)),
                int(record.get("child_id", pos)),
                int(bool(record.get("is_hierarchical", False))),
                int(bool(record.get("is_contextual", False))),
                json.dumps(record.get("metadata") or metadata or {}, ensure_ascii=False),
                int(has_vector),
            ),
        )
        conn.execute(
            "INSERT INTO chunk_fts(chunk_id, document_id, dataset_id, document_name, content) VALUES (?, ?, ?, ?, ?)",
            (
                chunk_id,
                document_id,
                dataset_id,
                morph.tokenize_for_index(name or ""),
                morph.tokenize_for_index(content or ""),
            ),
        )


def fts_search(conn: sqlite3.Connection, query: str, dataset_ids: list[str], limit: int, metadata_condition: dict | None = None) -> list[dict]:
    if not dataset_ids:
        return []
    match_expr = morph.tokenize_for_query(query)
    if not match_expr:
        return []
    placeholders = ",".join("?" * len(dataset_ids))
    rows = conn.execute(
        f"""
        SELECT c.chunk_id, c.document_id, c.dataset_id, d.name, c.position, c.content,
               bm25(chunk_fts) AS score,
               snippet(chunk_fts, 4, '<<', '>>', ' ... ', 24) AS snippet
        FROM chunk_fts
        JOIN chunks c ON c.chunk_id = chunk_fts.chunk_id
        JOIN documents d ON d.document_id = c.document_id
        WHERE chunk_fts MATCH ? AND c.dataset_id IN ({placeholders})
        ORDER BY score LIMIT ?
        """,
        [match_expr, *dataset_ids, limit],
    ).fetchall()
    cols = ["chunk_id", "document_id", "dataset_id", "document_name", "position", "content", "score", "snippet"]
    return _filter_metadata([dict(zip(cols, row)) for row in rows], metadata_condition)


def fetch_chunks(conn: sqlite3.Connection, chunk_ids: list[str]) -> dict[str, dict]:
    if not chunk_ids:
        return {}
    placeholders = ",".join("?" * len(chunk_ids))
    rows = conn.execute(
        f"""
        SELECT c.chunk_id, c.document_id, c.dataset_id, d.name, c.position, c.content,
               c.original_content, c.parent_content, c.parent_id, c.child_id,
               c.is_hierarchical, c.is_contextual, c.metadata_json
        FROM chunks c JOIN documents d ON d.document_id = c.document_id
        WHERE c.chunk_id IN ({placeholders})
        """,
        chunk_ids,
    ).fetchall()
    cols = ["chunk_id", "document_id", "dataset_id", "document_name", "position", "content", "original_content", "parent_content", "parent_id", "child_id", "is_hierarchical", "is_contextual", "metadata_json"]
    out = {}
    for row in rows:
        item = dict(zip(cols, row))
        try:
            item["metadata"] = __import__("json").loads(item.pop("metadata_json") or "{}")
        except Exception:
            item["metadata"] = {}
        item["is_hierarchical"] = bool(item["is_hierarchical"])
        item["is_contextual"] = bool(item["is_contextual"])
        out[row[0]] = item
    return out


def _filter_metadata(rows: list[dict], metadata_condition: dict | None) -> list[dict]:
    if not metadata_condition:
        return rows
    out = []
    for row in rows:
        match = True
        # Try to find metadata in 'metadata' key (which comes from metadata_json)
        # or top-level row fields
        try:
            row_meta = row.get("metadata") or {}
        except:
            row_meta = {}

        for k, v in metadata_condition.items():
            # Check row fields first (document_id, dataset_id, name, etc.)
            # then check inside the metadata blob
            actual = row.get(k)
            if actual is None:
                actual = row_meta.get(k)
            
            if str(actual) != str(v):
                match = False
                break
        if match:
            out.append(row)
    return out


def open_qdrant(cfg: Config):
    from qdrant_client import QdrantClient

    cfg.ensure_dirs()
    return QdrantClient(path=str(cfg.vector_db_path))


def ensure_collection(client, cfg: Config) -> None:
    from qdrant_client.http import models as qm

    distance = getattr(qm.Distance, cfg.qdrant.distance.upper(), qm.Distance.COSINE)
    existing = {c.name for c in client.get_collections().collections}
    if cfg.qdrant.collection not in existing:
        client.create_collection(
            collection_name=cfg.qdrant.collection,
            vectors_config=qm.VectorParams(size=cfg.embedding.dim, distance=distance),
        )


def upsert_vectors(client, cfg: Config, rows: list[tuple[str, list[float], dict]]) -> None:
    from qdrant_client.http import models as qm

    if not rows:
        return
    client.upsert(
        collection_name=cfg.qdrant.collection,
        points=[qm.PointStruct(id=qdrant_id(chunk_id), vector=vector, payload={"chunk_id": chunk_id, **payload}) for chunk_id, vector, payload in rows],
    )


def vector_search(client, cfg: Config, vector: list[float], dataset_ids: list[str], limit: int) -> list[dict]:
    from qdrant_client.http import models as qm

    query_filter = qm.Filter(must=[qm.FieldCondition(key="dataset_id", match=qm.MatchAny(any=dataset_ids))]) if dataset_ids else None
    if hasattr(client, "search"):
        response = client.search(
            collection_name=cfg.qdrant.collection,
            query_vector=vector,
            limit=limit,
            with_payload=True,
            query_filter=query_filter,
        )
    else:
        result = client.query_points(
            collection_name=cfg.qdrant.collection,
            query=vector,
            limit=limit,
            with_payload=True,
            query_filter=query_filter,
        )
        response = result.points
    return [{"chunk_id": h.payload.get("chunk_id"), "score": float(h.score), "payload": h.payload} for h in response if h.payload and h.payload.get("chunk_id")]


def qdrant_id(value: str) -> int:
    return int(hashlib.md5(value.encode("utf-8")).hexdigest()[:15], 16)
