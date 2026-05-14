"""Embedded Kùzu property-graph layer (no Docker, single directory DB).

Nodes  : Dataset, Document, Chunk
Edges  : (Document)-[:IN_DATASET]->(Dataset)
         (Document)-[:HAS_CHUNK]->(Chunk)
         (Chunk)-[:NEXT]->(Chunk)

We keep the SQLite tables as the source of truth; the graph is a secondary,
rebuildable index. `rebuild_from_sqlite()` wipes and re-loads it from the
canonical chunks/documents/datasets state.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import kuzu

from .config import Config

_lock = threading.Lock()
_db = None
_conn = None
_opened_path: str | None = None


def graph_path(cfg: Config) -> Path:
    return cfg.data_root / "GraphDB"


def open_graph(cfg: Config):
    """Return a process-wide cached (Database, Connection). Re-opens if the
    target path changed (mostly for tests)."""
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
    "CREATE REL TABLE IF NOT EXISTS IN_DATASET(FROM Document TO Dataset)",
    "CREATE REL TABLE IF NOT EXISTS HAS_CHUNK(FROM Document TO Chunk)",
    "CREATE REL TABLE IF NOT EXISTS NEXT(FROM Chunk TO Chunk)",
]


def _ensure_schema(conn) -> None:
    for ddl in _SCHEMA_DDL:
        conn.execute(ddl)


def rebuild_from_sqlite(graph_conn, sqlite_conn: sqlite3.Connection) -> dict:
    """Wipe the graph and re-load it from the SQLite state.

    Returns counts {datasets, documents, chunks, edges}.
    """
    # Drop all rows. Kùzu doesn't allow dropping rows referenced by a rel;
    # delete rels first, then nodes.
    for tbl in ("HAS_CHUNK", "NEXT", "IN_DATASET"):
        graph_conn.execute(f"MATCH ()-[r:{tbl}]->() DELETE r")
    for tbl in ("Chunk", "Document", "Dataset"):
        graph_conn.execute(f"MATCH (n:{tbl}) DELETE n")

    ds_rows = sqlite_conn.execute(
        "SELECT dataset_id, COALESCE(name, dataset_id) FROM datasets"
    ).fetchall()
    for ds_id, name in ds_rows:
        graph_conn.execute(
            "CREATE (n:Dataset {id: $id, name: $name})",
            {"id": ds_id, "name": name or ""},
        )

    doc_rows = sqlite_conn.execute(
        "SELECT document_id, dataset_id, name, source_path FROM documents"
    ).fetchall()
    for doc_id, ds_id, name, src in doc_rows:
        graph_conn.execute(
            "CREATE (n:Document {id: $id, name: $name, dataset_id: $ds, source_path: $src})",
            {"id": doc_id, "name": name or "", "ds": ds_id, "src": src or ""},
        )
        graph_conn.execute(
            """
            MATCH (d:Document), (s:Dataset)
            WHERE d.id = $did AND s.id = $sid
            CREATE (d)-[:IN_DATASET]->(s)
            """,
            {"did": doc_id, "sid": ds_id},
        )

    ch_rows = sqlite_conn.execute(
        "SELECT chunk_id, document_id, dataset_id, position FROM chunks ORDER BY document_id, position"
    ).fetchall()
    edges = 0
    prev_chunk: tuple[str, str] | None = None  # (chunk_id, document_id)
    for cid, doc_id, ds_id, pos in ch_rows:
        graph_conn.execute(
            "CREATE (n:Chunk {id: $id, document_id: $did, dataset_id: $sid, position: $pos})",
            {"id": cid, "did": doc_id, "sid": ds_id, "pos": int(pos or 0)},
        )
        graph_conn.execute(
            """
            MATCH (d:Document), (c:Chunk)
            WHERE d.id = $did AND c.id = $cid
            CREATE (d)-[:HAS_CHUNK]->(c)
            """,
            {"did": doc_id, "cid": cid},
        )
        edges += 1
        if prev_chunk is not None and prev_chunk[1] == doc_id:
            graph_conn.execute(
                """
                MATCH (a:Chunk), (b:Chunk)
                WHERE a.id = $a AND b.id = $b
                CREATE (a)-[:NEXT]->(b)
                """,
                {"a": prev_chunk[0], "b": cid},
            )
            edges += 1
        prev_chunk = (cid, doc_id)

    return {
        "datasets": len(ds_rows),
        "documents": len(doc_rows),
        "chunks": len(ch_rows),
        "edges": edges + len(doc_rows),  # IN_DATASET edges
    }


def run_query(conn, cypher: str, params: dict | None = None, limit: int = 50) -> dict:
    """Execute a read-only Cypher statement and return rows as plain dicts.

    Adds a safety LIMIT if the query doesn't have one. Read-only is enforced
    by rejecting statements that start with destructive keywords.
    """
    stripped = cypher.strip()
    head = stripped.split(None, 1)[0].upper() if stripped else ""
    if head in {"CREATE", "DELETE", "DROP", "ALTER", "MERGE", "SET"}:
        raise ValueError(
            f"graph_query is read-only — refusing to run '{head}'. "
            "Use the dedicated ingest path or graph_rebuild instead."
        )
    if " LIMIT " not in stripped.upper() and not stripped.upper().endswith(";"):
        cypher = f"{stripped} LIMIT {int(limit)}"
    result = conn.execute(cypher, params or {})
    cols = result.get_column_names()
    rows: list[dict] = []
    while result.has_next():
        values = result.get_next()
        rows.append({c: _serialize(v) for c, v in zip(cols, values)})
    return {"columns": cols, "rows": rows, "row_count": len(rows)}


def _serialize(value):
    # Kùzu returns native python values for primitives and dicts for nodes/rels
    if isinstance(value, dict):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
