"""Personalized PageRank engine over the Hippo2 entity+passage graph.

Edges contributing to the transition matrix:
- ``triples``         (RELATION, weighted by confidence)        — directed, but we
  symmetrise: a random-walk neighbour relationship is meaningful in both
  directions for Hippo2's retrieval signal.
- ``entity_synonyms`` (SYNONYM, weighted by cosine score)       — already symmetric.
- ``chunk_mentions``  (CONTEXT, weighted by mention count)      — connects
  Passage nodes to the Entity nodes found in that passage.

Algorithm: standard PPR power iteration
    r ← (1-α)·s + α·Mᵀ·r
where M is the row-stochastic adjacency. We use scipy sparse CSR for the
matrix and numpy float32 for the rank vector; on a 100k-node / 5M-edge
graph one iteration is ~10–30 ms on modern hardware.

Disk cache (``ppr_matrix.npz``):
- versioned by a ``graph_checksum`` (count + length sums of the source
  SQLite tables) so any node/edge change invalidates the cache.
- numpy ``.npz`` with ``allow_pickle=False``; loaded lazily on first
  ``run_ppr`` and reloaded when the checksum drifts.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy import sparse

from ..config import Config, Hippo2Config
from ..graph import graph_checksum

log = logging.getLogger(__name__)


def cache_path(cfg: Config) -> Path:
    return cfg.data_root / "ppr_matrix.npz"


@dataclass
class PPRMatrix:
    node_ids: list[str]        # row/col order; raw entity ids + passage:<chunk_id>
    entity_ids: list[str]
    passage_ids: list[str]
    index_of: dict[str, int]   # node id -> row index
    transition: sparse.csr_matrix  # row-stochastic, transposed for r ← α·Mᵀ·r
    checksum: str

    @property
    def n(self) -> int:
        return len(self.node_ids)


PASSAGE_PREFIX = "passage:"
CACHE_VERSION = 2


def passage_node_id(chunk_id: str) -> str:
    return f"{PASSAGE_PREFIX}{chunk_id}"


def is_passage_node_id(node_id: str) -> bool:
    return node_id.startswith(PASSAGE_PREFIX)


def chunk_id_from_passage_node(node_id: str) -> str:
    return node_id[len(PASSAGE_PREFIX):]


def _build_from_sqlite(sqlite_conn: sqlite3.Connection) -> PPRMatrix:
    """Build the row-stochastic transition matrix from SQLite state."""
    entity_rows = sqlite_conn.execute(
        "SELECT entity_id FROM entities ORDER BY entity_id"
    ).fetchall()
    entity_ids = [r[0] for r in entity_rows]
    passage_rows = sqlite_conn.execute(
        "SELECT chunk_id FROM chunks ORDER BY dataset_id, document_id, position"
    ).fetchall()
    passage_ids = [passage_node_id(r[0]) for r in passage_rows]
    node_ids = entity_ids + passage_ids
    index_of = {node_id: i for i, node_id in enumerate(node_ids)}
    n = len(node_ids)
    if n == 0:
        return PPRMatrix([], [], [], {}, sparse.csr_matrix((0, 0), dtype=np.float32), graph_checksum(sqlite_conn))

    rows: list[int] = []
    cols: list[int] = []
    data: list[float] = []

    for subj_id, obj_id, conf in sqlite_conn.execute(
        "SELECT subj_id, obj_id, confidence FROM triples"
    ):
        si = index_of.get(subj_id)
        oi = index_of.get(obj_id)
        if si is None or oi is None or si == oi:
            continue
        w = float(conf or 1.0)
        rows.append(si); cols.append(oi); data.append(w)
        rows.append(oi); cols.append(si); data.append(w)

    for a_id, b_id, score in sqlite_conn.execute(
        "SELECT a_id, b_id, score FROM entity_synonyms"
    ):
        ai = index_of.get(a_id)
        bi = index_of.get(b_id)
        if ai is None or bi is None or ai == bi:
            continue
        rows.append(ai); cols.append(bi); data.append(float(score))

    for chunk_id, entity_id, count in sqlite_conn.execute(
        "SELECT chunk_id, entity_id, count FROM chunk_mentions"
    ):
        pi = index_of.get(passage_node_id(chunk_id))
        ei = index_of.get(entity_id)
        if pi is None or ei is None or pi == ei:
            continue
        weight = float(np.log1p(int(count or 1)))
        rows.append(pi); cols.append(ei); data.append(weight)
        rows.append(ei); cols.append(pi); data.append(weight)

    if not data:
        # No edges → identity transition (random walk stays put). PPR
        # collapses to s, which still gives a useful retrieval ordering
        # via the linker scores alone.
        M = sparse.eye(n, dtype=np.float32, format="csr")
    else:
        adj = sparse.coo_matrix((data, (rows, cols)), shape=(n, n), dtype=np.float32).tocsr()
        # row-normalise
        deg = np.asarray(adj.sum(axis=1)).ravel()
        deg[deg == 0.0] = 1.0
        inv_deg = sparse.diags(1.0 / deg, dtype=np.float32)
        M = (inv_deg @ adj).tocsr()
    # We iterate r ← α·Mᵀ·r so cache the transpose once.
    M_t = M.T.tocsr()
    return PPRMatrix(
        node_ids=node_ids,
        entity_ids=entity_ids,
        passage_ids=passage_ids,
        index_of=index_of,
        transition=M_t,
        checksum=graph_checksum(sqlite_conn),
    )


def _save_cache(path: Path, m: PPRMatrix) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        path,
        version=np.array(CACHE_VERSION, dtype=np.int64),
        node_ids=np.array(m.node_ids, dtype=object),
        entity_ids=np.array(m.entity_ids, dtype=object),
        passage_ids=np.array(m.passage_ids, dtype=object),
        indptr=m.transition.indptr,
        indices=m.transition.indices,
        data=m.transition.data,
        shape=np.array(m.transition.shape, dtype=np.int64),
        checksum=np.array(m.checksum, dtype=object),
    )


def _load_cache(path: Path) -> PPRMatrix | None:
    if not path.exists():
        return None
    try:
        with np.load(path, allow_pickle=True) as bundle:
            version = int(bundle["version"].tolist()) if "version" in bundle else 0
            if version != CACHE_VERSION:
                return None
            node_ids = list(bundle["node_ids"].tolist())
            entity_ids = list(bundle["entity_ids"].tolist())
            passage_ids = list(bundle["passage_ids"].tolist())
            shape = tuple(int(x) for x in bundle["shape"])
            transition = sparse.csr_matrix(
                (bundle["data"], bundle["indices"], bundle["indptr"]),
                shape=shape,
                dtype=np.float32,
            )
            checksum = str(bundle["checksum"].tolist())
        return PPRMatrix(
            node_ids=node_ids,
            entity_ids=entity_ids,
            passage_ids=passage_ids,
            index_of={node_id: i for i, node_id in enumerate(node_ids)},
            transition=transition,
            checksum=checksum,
        )
    except Exception as exc:  # noqa: BLE001 — corrupt cache → ignore and rebuild
        log.warning("ppr cache load failed (%s); will rebuild", exc)
        return None


class PPREngine:
    """Process-wide singleton-ish PPR engine.

    Holds the in-memory CSR matrix and reloads it when the SQLite checksum
    drifts. Thread-safe via a single coarse lock — the hot path is matrix
    multiplication so lock contention is negligible.
    """

    def __init__(self, cfg: Config, hippo2_cfg: Hippo2Config) -> None:
        self.cfg = cfg
        self.hippo2_cfg = hippo2_cfg
        self._lock = threading.Lock()
        self._matrix: PPRMatrix | None = None

    def _ensure_matrix(self, sqlite_conn: sqlite3.Connection) -> PPRMatrix:
        current = graph_checksum(sqlite_conn)
        if self._matrix is not None and self._matrix.checksum == current:
            return self._matrix
        # Try disk cache first
        cached = _load_cache(cache_path(self.cfg))
        if cached is not None and cached.checksum == current:
            self._matrix = cached
            return cached
        log.info("rebuilding PPR matrix (checksum=%s)", current[:12])
        m = _build_from_sqlite(sqlite_conn)
        _save_cache(cache_path(self.cfg), m)
        self._matrix = m
        return m

    def warm(self, sqlite_conn: sqlite3.Connection) -> dict:
        with self._lock:
            m = self._ensure_matrix(sqlite_conn)
        return {
            "nodes": m.n,
            "entities": len(m.entity_ids),
            "passages": len(m.passage_ids),
            "nnz": int(m.transition.nnz),
            "checksum": m.checksum,
            "cache_path": str(cache_path(self.cfg)),
        }

    def invalidate(self) -> None:
        with self._lock:
            self._matrix = None

    def run_ppr(
        self,
        sqlite_conn: sqlite3.Connection,
        seeds: dict[str, float],
    ) -> dict[str, float]:
        """Run personalized PageRank from a seed distribution.

        ``seeds`` maps node_id → seed weight (will be re-normalised).
        Entity seeds use raw entity ids; passage seeds use ``passage:<chunk_id>``.
        Returns a dict mapping node_id → rank for non-zero entries only.
        """
        if not seeds:
            return {}
        with self._lock:
            m = self._ensure_matrix(sqlite_conn)
        if m.n == 0:
            return {}
        s = np.zeros(m.n, dtype=np.float32)
        total = 0.0
        for node_id, w in seeds.items():
            i = m.index_of.get(node_id)
            if i is None or w <= 0:
                continue
            s[i] += float(w)
            total += float(w)
        if total <= 0:
            return {}
        s /= total

        alpha = float(self.hippo2_cfg.ppr_alpha)
        tol = float(self.hippo2_cfg.ppr_tol)
        max_iter = max(1, int(self.hippo2_cfg.ppr_max_iter))

        r = s.copy()
        Mt = m.transition  # already transposed
        for _ in range(max_iter):
            r_next = (1.0 - alpha) * s + alpha * Mt.dot(r)
            if np.linalg.norm(r_next - r, ord=1) < tol:
                r = r_next
                break
            r = r_next

        # Sparsify output: only entries that received any mass.
        out: dict[str, float] = {}
        nz = np.where(r > 0.0)[0]
        for i in nz:
            out[m.node_ids[int(i)]] = float(r[int(i)])
        return out
