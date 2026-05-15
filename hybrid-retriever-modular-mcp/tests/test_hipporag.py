"""HippoRAG end-to-end smoke tests.

These tests stub out the LLM (OpenIE + query-entity extraction) and the
embedding API by inserting triples/embeddings directly into SQLite. The
goal is to verify the retrieval math — canonicalisation, mention
bookkeeping, synonym construction, PPR convergence, chunk scoring — not
the LLM client itself (covered separately in test_config.py).
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retriever import graph, storage
from retriever.config import Config, HippoRAGConfig
from retriever.hipporag import entities as ent_mod
from retriever.hipporag import ppr as ppr_mod
from retriever.hipporag import query as query_mod
from retriever.hipporag import synonyms
from retriever.hipporag.openie import Triple


def _seed_dataset(conn) -> None:
    storage.ensure_dataset(conn, "demo", "demo")
    conn.execute(
        "INSERT INTO documents(document_id, dataset_id, name, source_path, content_path) "
        "VALUES(?,?,?,?,?)",
        ("doc1", "demo", "d1.txt", "/tmp/d1.txt", "/tmp/d1.txt"),
    )
    for pos, (cid, txt) in enumerate(
        [
            ("doc1:0", "Samsung Electronics is headquartered in Seoul."),
            ("doc1:1", "Apple is headquartered in Cupertino."),
            ("doc1:2", "Both companies sell smartphones."),
        ]
    ):
        conn.execute(
            "INSERT INTO chunks(chunk_id, document_id, dataset_id, position, content) "
            "VALUES(?,?,?,?,?)",
            (cid, "doc1", "demo", pos, txt),
        )
    conn.commit()


def _seed_fake_embedding(conn, eid: str, vec) -> None:
    arr = np.asarray(vec, dtype=np.float32)
    conn.execute(
        "INSERT INTO entity_embeddings(entity_id, model, dim, vector) VALUES(?,?,?,?)",
        (eid, "fake", len(arr), graph.pack_vector(arr)),
    )


class CanonicaliseTest(unittest.TestCase):
    def test_collapses_whitespace_and_punctuation(self) -> None:
        self.assertEqual(ent_mod.canonicalize("  Samsung  Electronics!!"), "samsung electronics")

    def test_strips_quotation_marks(self) -> None:
        self.assertEqual(ent_mod.canonicalize("\"OpenAI\""), "openai")

    def test_nfkc_normalises_fullwidth(self) -> None:
        self.assertEqual(ent_mod.canonicalize("ＡＢＣ"), "abc")

    def test_id_is_stable(self) -> None:
        a = ent_mod.entity_id_for(ent_mod.canonicalize("Samsung"))
        b = ent_mod.entity_id_for(ent_mod.canonicalize("samsung"))
        self.assertEqual(a, b)


class PersistTriplesTest(unittest.TestCase):
    def test_writes_entities_mentions_and_triples(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = Config(data_root=Path(td))
            cfg.ensure_dirs()
            with storage.sqlite_session(cfg) as conn:
                _seed_dataset(conn)
                written = ent_mod.persist_triples(
                    conn,
                    chunk_id="doc1:0",
                    document_id="doc1",
                    dataset_id="demo",
                    triples=[Triple("Samsung", "located in", "Seoul")],
                )
                self.assertEqual(written, 1)
                ents = conn.execute("SELECT canonical FROM entities ORDER BY canonical").fetchall()
                self.assertEqual([r[0] for r in ents], ["samsung", "seoul"])
                mentions = conn.execute(
                    "SELECT COUNT(*) FROM chunk_mentions WHERE chunk_id = 'doc1:0'"
                ).fetchone()[0]
                self.assertEqual(mentions, 2)

    def test_dedupe_within_chunk(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = Config(data_root=Path(td))
            cfg.ensure_dirs()
            with storage.sqlite_session(cfg) as conn:
                _seed_dataset(conn)
                # Same canonical triple twice — second insertion is a no-op.
                written = ent_mod.persist_triples(
                    conn,
                    chunk_id="doc1:0",
                    document_id="doc1",
                    dataset_id="demo",
                    triples=[
                        Triple("Samsung", "located in", "Seoul"),
                        Triple(" samsung ", "located in", "SEOUL"),
                    ],
                )
                self.assertEqual(written, 1)


class SynonymsTest(unittest.TestCase):
    def test_threshold_filters_below(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = Config(data_root=Path(td))
            cfg.ensure_dirs()
            with storage.sqlite_session(cfg) as conn:
                _seed_dataset(conn)
                # Two clusters: {a,b}≈[1,0,...], {c,d}≈[0,1,...]. Within a
                # cluster cosine≈1, across cosine≈0.
                for canon, vec in [
                    ("a", [1.0, 0.05, 0.0, 0.0]),
                    ("b", [1.0, 0.0, 0.05, 0.0]),
                    ("c", [0.0, 1.0, 0.0, 0.05]),
                    ("d", [0.05, 1.0, 0.0, 0.0]),
                ]:
                    eid = ent_mod.entity_id_for(canon)
                    conn.execute(
                        "INSERT INTO entities(entity_id, canonical, surface) VALUES(?,?,?)",
                        (eid, canon, canon),
                    )
                    _seed_fake_embedding(conn, eid, vec)
                hcfg = HippoRAGConfig(synonym_threshold=0.95, synonym_top_k=3)
                result = synonyms.rebuild_synonyms(conn, hcfg)
                self.assertEqual(result["entities"], 4)
                # Only intra-cluster pairs should pass threshold: {a,b} and {c,d}.
                pairs = conn.execute(
                    "SELECT a_id, b_id FROM entity_synonyms"
                ).fetchall()
                # Expect 4 edges total (both directions of two distinct pairs).
                self.assertEqual(len(pairs), 4)


class PPREngineTest(unittest.TestCase):
    def test_pagerank_propagates_through_relations(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = Config(data_root=Path(td))
            cfg.ensure_dirs()
            with storage.sqlite_session(cfg) as conn:
                _seed_dataset(conn)
                # Two triples connect Samsung→Seoul, Apple→Cupertino.
                ent_mod.persist_triples(
                    conn, chunk_id="doc1:0", document_id="doc1", dataset_id="demo",
                    triples=[Triple("Samsung", "located in", "Seoul")],
                )
                ent_mod.persist_triples(
                    conn, chunk_id="doc1:1", document_id="doc1", dataset_id="demo",
                    triples=[Triple("Apple", "located in", "Cupertino")],
                )
                hcfg = HippoRAGConfig(synonym_threshold=2.0)  # disable synonyms
                engine = ppr_mod.PPREngine(cfg, hcfg)
                samsung_id = ent_mod.entity_id_for("samsung")
                scores = engine.run_ppr(conn, {samsung_id: 1.0})
                # Samsung and Seoul should both score >0; Apple and
                # Cupertino are in a disconnected component so they get
                # the (1-α)·s = 0 baseline only.
                seoul_id = ent_mod.entity_id_for("seoul")
                apple_id = ent_mod.entity_id_for("apple")
                self.assertGreater(scores.get(samsung_id, 0.0), 0.0)
                self.assertGreater(scores.get(seoul_id, 0.0), 0.0)
                self.assertEqual(scores.get(apple_id, 0.0), 0.0)

    def test_cache_invalidates_when_graph_changes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = Config(data_root=Path(td))
            cfg.ensure_dirs()
            with storage.sqlite_session(cfg) as conn:
                _seed_dataset(conn)
                ent_mod.persist_triples(
                    conn, chunk_id="doc1:0", document_id="doc1", dataset_id="demo",
                    triples=[Triple("Samsung", "located in", "Seoul")],
                )
                engine = ppr_mod.PPREngine(cfg, HippoRAGConfig())
                warm1 = engine.warm(conn)
                # add a new triple → checksum drift → matrix must rebuild
                ent_mod.persist_triples(
                    conn, chunk_id="doc1:1", document_id="doc1", dataset_id="demo",
                    triples=[Triple("Apple", "located in", "Cupertino")],
                )
                conn.commit()
                warm2 = engine.warm(conn)
                self.assertNotEqual(warm1["checksum"], warm2["checksum"])
                self.assertGreater(warm2["entities"], warm1["entities"])


class QueryScoringTest(unittest.TestCase):
    def test_chunks_ranked_by_mention_weighted_ppr(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = Config(data_root=Path(td))
            cfg.ensure_dirs()
            with storage.sqlite_session(cfg) as conn:
                _seed_dataset(conn)
                ent_mod.persist_triples(
                    conn, chunk_id="doc1:0", document_id="doc1", dataset_id="demo",
                    triples=[Triple("Samsung", "sells", "smartphones")],
                )
                ent_mod.persist_triples(
                    conn, chunk_id="doc1:1", document_id="doc1", dataset_id="demo",
                    triples=[Triple("Apple", "sells", "smartphones")],
                )
                # Hand-crafted PPR distribution: Samsung dominant, Apple = 0.
                samsung_id = ent_mod.entity_id_for("samsung")
                apple_id = ent_mod.entity_id_for("apple")
                fake_ppr = {samsung_id: 0.7, apple_id: 0.0}
                chunks = query_mod.score_chunks(conn, fake_ppr, ["demo"], top_chunks=5)
                # Only doc1:0 mentions Samsung; doc1:1 mentions Apple (mass 0).
                ids = [c["chunk_id"] for c in chunks]
                self.assertEqual(ids[0], "doc1:0")
                self.assertNotIn("doc1:1", ids)


if __name__ == "__main__":
    unittest.main()
