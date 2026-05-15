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


def has_pending_sync(conn: sqlite3.Connection) -> bool:
    for table in _SYNCED_TABLES:
        row = conn.execute(
            f"SELECT 1 FROM {table} WHERE kuzu_synced = 0 LIMIT 1"
        ).fetchone()
        if row:
            return True
    return False


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

    # Full rebuild: everything is now consistent with Kùzu. Flag for the
    # incremental sync path so the next ``graph_sync`` only sees diffs.
    _mark_all_synced(sqlite_conn)
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


_SYNCED_TABLES = (
    "datasets", "documents", "chunks", "entities", "triples",
    "chunk_mentions", "entity_synonyms",
)


def _mark_all_synced(sqlite_conn: sqlite3.Connection) -> None:
    for table in _SYNCED_TABLES:
        sqlite_conn.execute(f"UPDATE {table} SET kuzu_synced = 1 WHERE kuzu_synced = 0")


def _mark_synced(sqlite_conn: sqlite3.Connection, table: str, ids: list, pk_columns: list[str]) -> None:
    """Flip ``kuzu_synced`` for specific rows. ``ids`` is a list of tuples
    matching ``pk_columns`` (multi-column PK supported)."""
    if not ids:
        return
    where = " AND ".join(f"{col} = ?" for col in pk_columns)
    sql = f"UPDATE {table} SET kuzu_synced = 1 WHERE {where}"
    sqlite_conn.executemany(sql, ids)


def incremental_sync(graph_conn, sqlite_conn: sqlite3.Connection) -> dict:
    """Push only un-synced SQLite rows into Kùzu via bulk COPY FROM CSVs.

    Per-table ordering (nodes before their edges):
        Dataset → Document → IN_DATASET → Chunk → HAS_CHUNK → NEXT →
        Entity → MENTIONS → RELATION → SYNONYM (full-refresh)

    SYNONYM is full-refreshed (wipe + reload) instead of incremental: it is
    rebuilt as an all-pairs operation by ``rebuild_synonyms``, so a "diff"
    isn't well-defined and the table is small enough that a wipe-and-COPY
    costs less than the bookkeeping for incremental updates.

    Returns per-table counts of rows newly projected.
    """
    counts: dict[str, int] = {}

    with _staging_dir() as stage:
        # --- datasets ---
        ds_rows = sqlite_conn.execute(
            "SELECT dataset_id, COALESCE(name, dataset_id) FROM datasets WHERE kuzu_synced = 0"
        ).fetchall()
        ds_csv = stage / "datasets.csv"
        counts["Dataset"] = _dump_csv(ds_csv, ((r[0], r[1] or "") for r in ds_rows))
        _copy(graph_conn, "Dataset", ds_csv, counts["Dataset"] > 0)

        # --- documents + IN_DATASET ---
        doc_rows = sqlite_conn.execute(
            "SELECT document_id, dataset_id, name, source_path FROM documents WHERE kuzu_synced = 0"
        ).fetchall()
        doc_csv = stage / "documents.csv"
        counts["Document"] = _dump_csv(
            doc_csv,
            ((r[0], r[2] or "", r[1], r[3] or "") for r in doc_rows),
        )
        _copy(graph_conn, "Document", doc_csv, counts["Document"] > 0)

        in_ds_csv = stage / "in_dataset.csv"
        counts["IN_DATASET"] = _dump_csv(in_ds_csv, ((r[0], r[1]) for r in doc_rows))
        _copy(graph_conn, "IN_DATASET", in_ds_csv, counts["IN_DATASET"] > 0)

        # --- chunks + HAS_CHUNK + NEXT ---
        chunk_rows = sqlite_conn.execute(
            "SELECT chunk_id, document_id, dataset_id, position FROM chunks "
            "WHERE kuzu_synced = 0 ORDER BY document_id, position"
        ).fetchall()
        ch_csv = stage / "chunks.csv"
        counts["Chunk"] = _dump_csv(
            ch_csv,
            ((cid, did, sid, int(pos or 0)) for cid, did, sid, pos in chunk_rows),
        )
        _copy(graph_conn, "Chunk", ch_csv, counts["Chunk"] > 0)

        has_chunk_csv = stage / "has_chunk.csv"
        counts["HAS_CHUNK"] = _dump_csv(
            has_chunk_csv, ((did, cid) for cid, did, _sid, _pos in chunk_rows)
        )
        _copy(graph_conn, "HAS_CHUNK", has_chunk_csv, counts["HAS_CHUNK"] > 0)

        # NEXT edges are intra-document; safe to derive only from the new
        # chunks because re-uploads of an existing document delete its old
        # chunks first, so every "previous" chunk for a new chunk is also
        # new in this batch.
        next_rows: list[tuple[str, str]] = []
        prev: tuple[str, str] | None = None
        for cid, did, _sid, _pos in chunk_rows:
            if prev is not None and prev[1] == did:
                next_rows.append((prev[0], cid))
            prev = (cid, did)
        next_csv = stage / "next.csv"
        counts["NEXT"] = _dump_csv(next_csv, iter(next_rows))
        _copy(graph_conn, "NEXT", next_csv, counts["NEXT"] > 0)

        # --- entities (shared across documents — ON CONFLICT DO NOTHING in
        # ``upsert_entity`` preserves an entity's existing kuzu_synced=1, so
        # we never re-COPY an already-projected entity).
        ent_rows = sqlite_conn.execute(
            "SELECT entity_id, canonical, surface, type FROM entities WHERE kuzu_synced = 0"
        ).fetchall()
        ent_csv = stage / "entities.csv"
        counts["Entity"] = _dump_csv(
            ent_csv,
            ((eid, canon or "", surface or "", etype or "") for eid, canon, surface, etype in ent_rows),
        )
        _copy(graph_conn, "Entity", ent_csv, counts["Entity"] > 0)

        # --- MENTIONS ---
        mention_rows = sqlite_conn.execute(
            "SELECT chunk_id, entity_id, count FROM chunk_mentions WHERE kuzu_synced = 0"
        ).fetchall()
        mentions_csv = stage / "mentions.csv"
        counts["MENTIONS"] = _dump_csv(
            mentions_csv, ((cid, eid, int(cnt or 1)) for cid, eid, cnt in mention_rows)
        )
        _copy(graph_conn, "MENTIONS", mentions_csv, counts["MENTIONS"] > 0)

        # --- RELATION ---
        triple_rows = sqlite_conn.execute(
            "SELECT triple_id, subj_id, obj_id, pred, confidence FROM triples WHERE kuzu_synced = 0"
        ).fetchall()
        rel_csv = stage / "relations.csv"
        counts["RELATION"] = _dump_csv(
            rel_csv,
            ((subj, obj, pred or "", float(conf or 1.0)) for _tid, subj, obj, pred, conf in triple_rows),
        )
        _copy(graph_conn, "RELATION", rel_csv, counts["RELATION"] > 0)

        # --- SYNONYM full refresh ---
        # rebuild_synonyms() wipes and re-inserts entity_synonyms wholesale,
        # so any synced=0 row in this table means the synonym graph has
        # drifted. Cheaper to wipe Kùzu SYNONYM and replay than to compute
        # an actual diff.
        unsynced_syn = sqlite_conn.execute(
            "SELECT COUNT(*) FROM entity_synonyms WHERE kuzu_synced = 0"
        ).fetchone()[0]
        if unsynced_syn > 0:
            graph_conn.execute("MATCH ()-[r:SYNONYM]->() DELETE r")
            syn_rows = sqlite_conn.execute(
                "SELECT a_id, b_id, score FROM entity_synonyms"
            ).fetchall()
            syn_csv = stage / "synonyms.csv"
            counts["SYNONYM"] = _dump_csv(
                syn_csv, ((a, b, float(s)) for a, b, s in syn_rows)
            )
            _copy(graph_conn, "SYNONYM", syn_csv, counts["SYNONYM"] > 0)
        else:
            counts["SYNONYM"] = 0

    # Flip kuzu_synced=1 for every row we just projected.
    _mark_synced(sqlite_conn, "datasets", [(r[0],) for r in ds_rows], ["dataset_id"])
    _mark_synced(sqlite_conn, "documents", [(r[0],) for r in doc_rows], ["document_id"])
    _mark_synced(sqlite_conn, "chunks", [(r[0],) for r in chunk_rows], ["chunk_id"])
    _mark_synced(sqlite_conn, "entities", [(r[0],) for r in ent_rows], ["entity_id"])
    _mark_synced(sqlite_conn, "chunk_mentions",
                 [(r[0], r[1]) for r in mention_rows], ["chunk_id", "entity_id"])
    _mark_synced(sqlite_conn, "triples", [(r[0],) for r in triple_rows], ["triple_id"])
    if unsynced_syn > 0:
        sqlite_conn.execute("UPDATE entity_synonyms SET kuzu_synced = 1")

    set_state(sqlite_conn, "dirty", "0")
    set_state(sqlite_conn, "last_sync_at", datetime.utcnow().isoformat() + "Z")
    set_state(sqlite_conn, "checksum", graph_checksum(sqlite_conn))

    return {
        "mode": "incremental",
        "datasets": counts["Dataset"],
        "documents": counts["Document"],
        "chunks": counts["Chunk"],
        "entities": counts["Entity"],
        "edges": (
            counts["IN_DATASET"] + counts["HAS_CHUNK"] + counts["NEXT"]
            + counts["MENTIONS"] + counts["RELATION"] + counts["SYNONYM"]
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


def sync_graph(graph_conn, sqlite_conn: sqlite3.Connection) -> dict:
    """Bring Kuzu in sync with SQLite, incrementally when safe.

    ``dirty=1`` means SQLite changes included deletes or replacements, so the
    graph needs a full replay. Otherwise we can push only rows where
    ``kuzu_synced=0``.
    """
    if is_dirty(sqlite_conn):
        result = rebuild_from_sqlite(graph_conn, sqlite_conn)
        result["mode"] = "rebuild"
        return result
    if has_pending_sync(sqlite_conn):
        return incremental_sync(graph_conn, sqlite_conn)
    return {"mode": "noop", "datasets": 0, "documents": 0, "chunks": 0, "entities": 0, "edges": 0, "edge_breakdown": {}}


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
