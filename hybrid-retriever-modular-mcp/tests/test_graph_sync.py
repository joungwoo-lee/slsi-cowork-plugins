from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retriever import graph, storage
from retriever.config import Config


class GraphSyncRoutingTest(unittest.TestCase):
    def test_incremental_used_for_unsynced_inserts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = Config(data_root=Path(td))
            cfg.ensure_dirs()
            with storage.sqlite_session(cfg) as conn:
                storage.ensure_dataset(conn, "demo", "demo")
                graph.set_state(conn, "dirty", "0")
                conn.execute(
                    "INSERT INTO documents(document_id, dataset_id, name, source_path, content_path) VALUES(?,?,?,?,?)",
                    ("doc1", "demo", "d1.txt", "src", "content"),
                )
                self.assertFalse(graph.is_dirty(conn))
                self.assertTrue(graph.has_pending_sync(conn))

                calls: list[str] = []
                old_incremental = graph.incremental_sync
                old_rebuild = graph.rebuild_from_sqlite
                try:
                    graph.incremental_sync = lambda _g, _c: calls.append("incremental") or {"mode": "incremental"}
                    graph.rebuild_from_sqlite = lambda _g, _c: calls.append("rebuild") or {"mode": "rebuild"}
                    result = graph.sync_graph(object(), conn)
                finally:
                    graph.incremental_sync = old_incremental
                    graph.rebuild_from_sqlite = old_rebuild

                self.assertEqual(calls, ["incremental"])
                self.assertEqual(result["mode"], "incremental")

    def test_rebuild_used_when_dirty(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = Config(data_root=Path(td))
            cfg.ensure_dirs()
            with storage.sqlite_session(cfg) as conn:
                storage.ensure_dataset(conn, "demo", "demo")
                graph.mark_dirty(conn)

                calls: list[str] = []
                old_incremental = graph.incremental_sync
                old_rebuild = graph.rebuild_from_sqlite
                try:
                    graph.incremental_sync = lambda _g, _c: calls.append("incremental") or {"mode": "incremental"}
                    graph.rebuild_from_sqlite = lambda _g, _c: calls.append("rebuild") or {"mode": "rebuild"}
                    result = graph.sync_graph(object(), conn)
                finally:
                    graph.incremental_sync = old_incremental
                    graph.rebuild_from_sqlite = old_rebuild

                self.assertEqual(calls, ["rebuild"])
                self.assertEqual(result["mode"], "rebuild")


class UpsertDocumentDirtyTest(unittest.TestCase):
    def test_reupload_marks_graph_dirty(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = Config(data_root=Path(td))
            cfg.ensure_dirs()
            with storage.sqlite_session(cfg) as conn:
                storage.ensure_dataset(conn, "demo", "demo")
                graph.set_state(conn, "dirty", "0")
                storage.upsert_document(
                    conn,
                    dataset_id="demo",
                    document_id="doc1",
                    name="a.txt",
                    source_path="src",
                    content_path="content",
                    size_bytes=1,
                    chunks=[{"child_content": "one"}],
                )
                self.assertFalse(graph.is_dirty(conn))

                conn.execute("UPDATE documents SET kuzu_synced = 1 WHERE document_id = ?", ("doc1",))
                conn.execute("UPDATE chunks SET kuzu_synced = 1 WHERE document_id = ?", ("doc1",))
                conn.commit()

                storage.upsert_document(
                    conn,
                    dataset_id="demo",
                    document_id="doc1",
                    name="a.txt",
                    source_path="src",
                    content_path="content",
                    size_bytes=2,
                    chunks=[{"child_content": "two"}],
                )
                self.assertTrue(graph.is_dirty(conn))
                synced = conn.execute(
                    "SELECT kuzu_synced FROM documents WHERE document_id = ?",
                    ("doc1",),
                ).fetchone()[0]
                self.assertEqual(int(synced), 0)


if __name__ == "__main__":
    unittest.main()
