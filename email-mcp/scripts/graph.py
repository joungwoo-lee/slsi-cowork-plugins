"""Embedded Kùzu property-graph layer for email-mcp.

Nodes  : Mail, Person
Edges  : (Person)-[:SENT]->(Mail)
         (Person)-[:RECEIVED]->(Mail)

The SQLite tables remain the source of truth; `rebuild_from_sqlite()` wipes
and re-populates the graph from mail_metadata.
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
    "CREATE NODE TABLE IF NOT EXISTS Mail(id STRING, subject STRING, received STRING, folder_path STRING, PRIMARY KEY(id))",
    "CREATE NODE TABLE IF NOT EXISTS Person(address STRING, PRIMARY KEY(address))",
    "CREATE REL TABLE IF NOT EXISTS SENT(FROM Person TO Mail)",
    "CREATE REL TABLE IF NOT EXISTS RECEIVED(FROM Person TO Mail)",
]


def _ensure_schema(conn) -> None:
    for ddl in _SCHEMA_DDL:
        conn.execute(ddl)


def _split_addresses(raw: str | None) -> list[str]:
    if not raw:
        return []
    out: list[str] = []
    for part in raw.replace(";", ",").split(","):
        addr = part.strip()
        if addr:
            out.append(addr)
    return out


def rebuild_from_sqlite(graph_conn, sqlite_conn: sqlite3.Connection) -> dict:
    """Wipe the graph and re-load from mail_metadata.

    Returns counts {mails, people, edges}.
    """
    for tbl in ("SENT", "RECEIVED"):
        graph_conn.execute(f"MATCH ()-[r:{tbl}]->() DELETE r")
    for tbl in ("Mail", "Person"):
        graph_conn.execute(f"MATCH (n:{tbl}) DELETE n")

    rows = sqlite_conn.execute(
        "SELECT mail_id, subject, sender, recipients, received, folder_path FROM mail_metadata"
    ).fetchall()

    people: set[str] = set()
    edge_count = 0
    for mail_id, subject, sender, recipients, received, folder in rows:
        graph_conn.execute(
            """
            CREATE (n:Mail {
                id: $id, subject: $subj, received: $rcv, folder_path: $folder
            })
            """,
            {"id": mail_id, "subj": subject or "", "rcv": received or "", "folder": folder or ""},
        )
        senders = _split_addresses(sender)
        recipients_list = _split_addresses(recipients)
        for addr in senders + recipients_list:
            if addr not in people:
                graph_conn.execute(
                    "CREATE (p:Person {address: $a})",
                    {"a": addr},
                )
                people.add(addr)
        for addr in senders:
            graph_conn.execute(
                """
                MATCH (p:Person), (m:Mail)
                WHERE p.address = $a AND m.id = $id
                CREATE (p)-[:SENT]->(m)
                """,
                {"a": addr, "id": mail_id},
            )
            edge_count += 1
        for addr in recipients_list:
            graph_conn.execute(
                """
                MATCH (p:Person), (m:Mail)
                WHERE p.address = $a AND m.id = $id
                CREATE (p)-[:RECEIVED]->(m)
                """,
                {"a": addr, "id": mail_id},
            )
            edge_count += 1

    return {"mails": len(rows), "people": len(people), "edges": edge_count}


def run_query(conn, cypher: str, params: dict | None = None, limit: int = 50) -> dict:
    stripped = cypher.strip()
    head = stripped.split(None, 1)[0].upper() if stripped else ""
    if head in {"CREATE", "DELETE", "DROP", "ALTER", "MERGE", "SET"}:
        raise ValueError(
            f"graph_query is read-only — refusing to run '{head}'. "
            "Use graph_rebuild for ingesting state."
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
    if isinstance(value, dict):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
