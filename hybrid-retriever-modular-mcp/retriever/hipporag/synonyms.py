"""Synonym edge construction from entity embeddings.

For every entity with a stored embedding we find its top-K nearest
neighbours by cosine similarity and emit an undirected SYNONYM edge for
each pair whose similarity exceeds ``HIPPORAG_SYNONYM_THRESHOLD``.

Implementation uses normalized numpy matmul in batches to bound memory:
peak working set is O(batch × N × 4 bytes). At N=100k entities and
batch=512 that's ~200 MB — comfortable on a workstation. Beyond N=500k
swap to a proper ANN library (faiss, hnswlib); this module is a single
swap-point.
"""
from __future__ import annotations

import logging
import sqlite3

import numpy as np

from ..config import HippoRAGConfig
from ..graph import unpack_vector

log = logging.getLogger(__name__)

_BATCH = 512


def _load_embedding_matrix(
    conn: sqlite3.Connection,
) -> tuple[list[str], np.ndarray, int]:
    """Return (entity_ids, normalized matrix [N, dim], dim).

    Empty matrix when no entity has an embedding yet.
    """
    rows = conn.execute(
        "SELECT entity_id, dim, vector FROM entity_embeddings"
    ).fetchall()
    if not rows:
        return [], np.zeros((0, 0), dtype=np.float32), 0
    dim = int(rows[0][1])
    if any(int(d) != dim for _eid, d, _v in rows):
        raise ValueError(
            "entity embeddings have mixed dims — re-run embed_pending_entities "
            "after model swap"
        )
    ids: list[str] = []
    mat = np.zeros((len(rows), dim), dtype=np.float32)
    for i, (eid, _d, blob) in enumerate(rows):
        ids.append(eid)
        mat[i] = np.asarray(unpack_vector(blob, dim), dtype=np.float32)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    mat /= norms
    return ids, mat, dim


def rebuild_synonyms(
    conn: sqlite3.Connection,
    hipporag_cfg: HippoRAGConfig,
) -> dict:
    """Wipe ``entity_synonyms`` and rebuild it from current embeddings.

    Returns counts ``{entities, edges, skipped}``.
    """
    ids, mat, dim = _load_embedding_matrix(conn)
    if mat.shape[0] < 2:
        conn.execute("DELETE FROM entity_synonyms")
        return {"entities": mat.shape[0], "edges": 0, "skipped": 0, "dim": dim}

    threshold = float(hipporag_cfg.synonym_threshold)
    top_k = max(1, int(hipporag_cfg.synonym_top_k))
    N = mat.shape[0]

    conn.execute("DELETE FROM entity_synonyms")
    edges = 0
    skipped = 0
    for start in range(0, N, _BATCH):
        end = min(N, start + _BATCH)
        block = mat[start:end]  # [B, dim]
        sims = block @ mat.T    # [B, N]
        for local_i, row in enumerate(sims):
            global_i = start + local_i
            row[global_i] = -1.0  # exclude self
            k = min(top_k, N - 1)
            if k <= 0:
                continue
            cand = np.argpartition(-row, k - 1)[:k]
            for j in cand:
                score = float(row[j])
                if score < threshold:
                    skipped += 1
                    continue
                a, b = ids[global_i], ids[int(j)]
                if a == b:
                    continue
                # Store both directions so PPR transitions are symmetric.
                conn.execute(
                    "INSERT INTO entity_synonyms(a_id, b_id, score) VALUES(?, ?, ?) "
                    "ON CONFLICT(a_id, b_id) DO UPDATE SET score = MAX(entity_synonyms.score, excluded.score)",
                    (a, b, score),
                )
                conn.execute(
                    "INSERT INTO entity_synonyms(a_id, b_id, score) VALUES(?, ?, ?) "
                    "ON CONFLICT(a_id, b_id) DO UPDATE SET score = MAX(entity_synonyms.score, excluded.score)",
                    (b, a, score),
                )
                edges += 1
        conn.commit()
        log.debug("synonyms batch %d-%d: edges=%d", start, end, edges)
    return {"entities": N, "edges": edges, "skipped": skipped, "dim": dim}
