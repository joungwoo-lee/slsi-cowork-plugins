"""Embedded Kùzu property-graph layer (no Docker, single directory DB).

Nodes  : Dataset, Document, Chunk, Entity
Edges  : (Document)-[:IN_DATASET]->(Dataset)
         (Document)-[:HAS_CHUNK]->(Chunk)
         (Chunk)-[:NEXT]->(Chunk)
         (Chunk)-[:MENTIONS]->(Entity)        — HippoRAG passage-entity link
         (Entity)-[:RELATION]->(Entity)        — OpenIE triples (predicate prop)
         (Entity)-[:SYNONYM]->(Entity)         — embedding-similarity edges

SQLite remains the source of truth; the graph is a secondary index.
``rebuild_from_sqlite`` wipes and re-loads it from the canonical state using
Kùzu's bulk ``COPY FROM`` against staged CSVs. With per-row Cypher ``CREATE``
the previous implementation cost ~3 round-trips per chunk; the bulk path is
typically 1-2 orders of magnitude faster on 10k+ chunks.
"""
from __future__ import annotations

import csv
import hashlib
import re
import sqlite3
import struct
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

import kuzu

from .config import Config

_LIMIT_RE = re.compile(r"\bLIMIT\s+\d+\b", re.IGNORECASE)
_DESTRUCTIVE_KEYWORDS = frozenset({"CREATE", "DELETE", "DROP", "ALTER", "MERGE", "SET", "REMOVE"})

_lock = threading.Lock()
_db = None
_conn = None
_opened_path: str | None = None


def graph_path(cfg: Config) -> Path:
    return cfg.data_root / "GraphDB"


def open_graph(cfg: Config):
    global _db, _conn, _opened_path
    target = str(graph_path(cfg))
    with _lock:
        if _conn is not None and _opened_path == target:
            return _conn
        cfg.ensure_dirs()
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        _db = kuzu.Database(target)
        _conn = kuzu.Connection(_db)
        _opened_path = target
        _ensure_schema(_conn)
    return _conn


def close_graph() -> None:
    global _db, _conn, _opened_path
    with _lock:
        _conn = None
        _db = None
        _opened_path = None


_SCHEMA_DDL = [
    "CREATE NODE TABLE IF NOT EXISTS Dataset(id STRING, name STRING, PRIMARY KEY(id))",
    "CREATE NODE TABLE IF NOT EXISTS Document(id STRING, name STRING, dataset_id STRING, source_path STRING, PRIMARY KEY(id))",
    "CREATE NODE TABLE IF NOT EXISTS Chunk(id STRING, document_id STRING, dataset_id STRING, position INT64, PRIMARY KEY(id))",
    "CREATE NODE TABLE IF NOT EXISTS Entity(id STRING, canonical STRING, surface STRING, type STRING, PRIMARY KEY(id))",
    "CREATE REL TABLE IF NOT EXISTS IN_DATASET(FROM Document TO Dataset)",
    "CREATE REL TABLE IF NOT EXISTS HAS_CHUNK(FROM Document TO Chunk)",
    "CREATE REL TABLE IF NOT EXISTS NEXT(FROM Chunk TO Chunk)",
    "CREATE REL TABLE IF NOT EXISTS MENTIONS(FROM Chunk TO Entity, count INT64)",
    "CREATE REL TABLE IF NOT EXISTS RELATION(FROM Entity TO Entity, predicate STRING, confidence DOUBLE)",
    "CREATE REL TABLE IF NOT EXISTS SYNONYM(FROM Entity TO Entity, score DOUBLE)",
]

_NODE_TABLES = ("Dataset", "Document", "Chunk", "Entity")
_REL_TABLES = ("IN_DATASET", "HAS_CHUNK", "NEXT", "MENTIONS", "RELATION", "SYNONYM")


def _ensure_schema(conn) -> None:
    for ddl in _SCHEMA_DDL:
        conn.execute(ddl)


# ----- graph state --------------------------------------------------------

def set_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO graph_state(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def get_state(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM graph_state WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def mark_dirty(conn: sqlite3.Connection) -> None:
    set_state(conn, "dirty", "1")


def is_dirty(conn: sqlite3.Connection) -> bool:
    return get_state(conn, "dirty", "1") == "1"


def graph_checksum(conn: sqlite3.Connection) -> str:
    """Cheap content fingerprint used by the PPR cache to detect staleness."""
    h = hashlib.sha256()
    for sql in (
        "SELECT COUNT(*), COALESCE(SUM(LENGTH(chunk_id)),0) FROM chunks",
        "SELECT COUNT(*), COALESCE(SUM(LENGTH(entity_id)),0) FROM entities",
        "SELECT COUNT(*), COALESCE(SUM(LENGTH(triple_id)),0) FROM triples",
        "SELECT COUNT(*) FROM entity_synonyms",
    ):
        for row in conn.execute(sql):
            h.update(repr(row).encode("utf-8"))
    return h.hexdigest()


# ----- bulk rebuild -------------------------------------------------------


@contextmanager
def _staging_dir() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="kuzu_stage_") as td:
        yield Path(td)


def _dump_csv(path: Path, rows: Iterator[tuple]) -> int:
    n = 0
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        for row in rows:
            writer.writerow(["" if v is None else v for v in row])
            n += 1
    return n


def _wipe_graph(graph_conn) -> None:
    for tbl in _REL_TABLES:
        graph_conn.execute(f"MATCH ()-[r:{tbl}]->() DELETE r")
    for tbl in _NODE_TABLES:
        graph_conn.execute(f"MATCH (n:{tbl}) DELETE n")


def _kuzu_path(p: Path) -> str:
    # Kùzu's parser is fussy about backslashes in quoted strings on Windows.
    return str(p).replace("\\", "/")


def _copy(graph_conn, table: str, csv_path: Path, has_rows: bool) -> None:
    if not has_rows:
        return
    graph_conn.execute(f"COPY {table} FROM '{_kuzu_path(csv_path)}'")


def rebuild_from_sqlite(graph_conn, sqlite_conn: sqlite3.Connection) -> dict:
    """Wipe the graph and bulk-reload it from SQLite via staged CSVs.

    Returns counts for each node/rel table. Marks ``graph_state.dirty`` = 0
    and records the new checksum so the PPR engine can invalidate its
    in-memory matrix.
    """
    _wipe_graph(graph_conn)

    counts: dict[str, int] = {}

    with _staging_dir() as stage:
        ds_csv = stage / "datasets.csv"
        counts["Dataset"] = _dump_csv(
            ds_csv,
            (
                (ds_id, name or "")
                for ds_id, name in sqlite_conn.execute(
                    "SELECT dataset_id, COALESCE(name, dataset_id) FROM datasets"
                )
            ),
        )

        doc_csv = stage / "documents.csv"
        counts["Document"] = _dump_csv(
            doc_csv,
            (
                (doc_id, name or "", ds_id, src or "")
                for doc_id, ds_id, name, src in sqlite_conn.execute(
                    "SELECT document_id, dataset_id, name, source_path FROM documents"
                )
            ),
        )

        chunk_rows = list(
            sqlite_conn.execute(
                "SELECT chunk_id, document_id, dataset_id, position FROM chunks "
                "ORDER BY document_id, position"
            )
        )
        ch_csv = stage / "chunks.csv"
        counts["Chunk"] = _dump_csv(
            ch_csv,
            ((cid, did, sid, int(pos or 0)) for cid, did, sid, pos in chunk_rows),
        )

        ent_csv = stage / "entities.csv"
        counts["Entity"] = _dump_csv(
            ent_csv,
            (
                (eid, canon or "", surface or "", etype or "")
                for eid, canon, surface, etype in sqlite_conn.execute(
                    "SELECT entity_id, canonical, surface, type FROM entities"
                )
            ),
        )

        _copy(graph_conn, "Dataset", ds_csv, counts["Dataset"] > 0)
        _copy(graph_conn, "Document", doc_csv, counts["Document"] > 0)
        _copy(graph_conn, "Chunk", ch_csv, counts["Chunk"] > 0)
        _copy(graph_conn, "Entity", ent_csv, counts["Entity"] > 0)

        in_ds_csv = stage / "in_dataset.csv"
        counts["IN_DATASET"] = _dump_csv(
            in_ds_csv,
            (
                (doc_id, ds_id)
                for doc_id, ds_id in sqlite_conn.execute(
                    "SELECT document_id, dataset_id FROM documents"
                )
            ),
        )

        has_chunk_csv = stage / "has_chunk.csv"
        counts["HAS_CHUNK"] = _dump_csv(
            has_chunk_csv,
            ((did, cid) for cid, did, _sid, _pos in chunk_rows),
        )

        next_rows: list[tuple[str, str]] = []
        prev: tuple[str, str] | None = None
        for cid, did, _sid, _pos in chunk_rows:
            if prev is not None and prev[1] == did:
                next_rows.append((prev[0], cid))
            prev = (cid, did)
        next_csv = stage / "next.csv"
        counts["NEXT"] = _dump_csv(next_csv, iter(next_rows))

        mentions_csv = stage / "mentions.csv"
        counts["MENTIONS"] = _dump_csv(
            mentions_csv,
            (
                (cid, eid, int(cnt or 1))
                for cid, eid, cnt in sqlite_conn.execute(
                    "SELECT chunk_id, entity_id, count FROM chunk_mentions"
                )
            ),
        )

        rel_csv = stage / "relations.csv"
        counts["RELATION"] = _dump_csv(
            rel_csv,
            (
                (subj_id, obj_id, pred or "", float(conf or 1.0))
                for subj_id, obj_id, pred, conf in sqlite_conn.execute(
                    "SELECT subj_id, obj_id, pred, confidence FROM triples"
                )
            ),
        )

        syn_csv = stage / "synonyms.csv"
        counts["SYNONYM"] = _dump_csv(
            syn_csv,
            (
                (a, b, float(s))
                for a, b, s in sqlite_conn.execute(
                    "SELECT a_id, b_id, score FROM entity_synonyms"
                )
            ),
        )

        _copy(graph_conn, "IN_DATASET", in_ds_csv, counts["IN_DATASET"] > 0)
        _copy(graph_conn, "HAS_CHUNK", has_chunk_csv, counts["HAS_CHUNK"] > 0)
        _copy(graph_conn, "NEXT", next_csv, counts["NEXT"] > 0)
        _copy(graph_conn, "MENTIONS", mentions_csv, counts["MENTIONS"] > 0)
        _copy(graph_conn, "RELATION", rel_csv, counts["RELATION"] > 0)
        _copy(graph_conn, "SYNONYM", syn_csv, counts["SYNONYM"] > 0)

    set_state(sqlite_conn, "dirty", "0")
    set_state(sqlite_conn, "last_rebuilt_at", datetime.utcnow().isoformat() + "Z")
    set_state(sqlite_conn, "checksum", graph_checksum(sqlite_conn))

    return {
        "datasets": counts["Dataset"],
        "documents": counts["Document"],
        "chunks": counts["Chunk"],
        "entities": counts["Entity"],
        "edges": (
            counts["IN_DATASET"]
            + counts["HAS_CHUNK"]
            + counts["NEXT"]
            + counts["MENTIONS"]
            + counts["RELATION"]
            + counts["SYNONYM"]
        ),
        "edge_breakdown": {
            "IN_DATASET": counts["IN_DATASET"],
            "HAS_CHUNK": counts["HAS_CHUNK"],
            "NEXT": counts["NEXT"],
            "MENTIONS": counts["MENTIONS"],
            "RELATION": counts["RELATION"],
            "SYNONYM": counts["SYNONYM"],
        },
    }


# ----- embedding blob helpers --------------------------------------------


def pack_vector(vec) -> bytes:
    return struct.pack(f"<{len(vec)}f", *(float(v) for v in vec))


def unpack_vector(blob: bytes, dim: int) -> list[float]:
    if len(blob) != dim * 4:
        raise ValueError(f"entity embedding blob size {len(blob)} != dim*4 ({dim*4})")
    return list(struct.unpack(f"<{dim}f", blob))


# ----- read-only Cypher --------------------------------------------------


def run_query(conn, cypher: str, params: dict | None = None, limit: int = 50) -> dict:
    stripped = cypher.strip().rstrip(";").strip()
    if not stripped:
        raise ValueError("cypher is empty")
    head = stripped.split(None, 1)[0].upper()
    if head in _DESTRUCTIVE_KEYWORDS:
        raise ValueError(
            f"graph_query is read-only — refusing to run '{head}'. "
            "Use the dedicated ingest path or graph_rebuild instead."
        )
    if not _LIMIT_RE.search(stripped):
        stripped = f"{stripped} LIMIT {int(limit)}"
    result = conn.execute(stripped, params or {})
    cols = result.get_column_names()
    rows: list[dict] = []
    while result.has_next():
        values = result.get_next()
        rows.append({c: _serialize(v) for c, v in zip(cols, values)})
    return {"columns": cols, "rows": rows, "row_count": len(rows)}


def _serialize(value):
    if isinstance(value, dict):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
