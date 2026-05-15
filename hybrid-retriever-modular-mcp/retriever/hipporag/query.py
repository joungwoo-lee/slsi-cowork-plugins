"""Query-side HippoRAG: extract query entities → link → PPR → score chunks."""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

import numpy as np

from ..config import Config, EmbeddingConfig, HippoRAGConfig, LLMConfig
from ..embedding_client import EmbeddingClient
from ..graph import unpack_vector
from ..llm_client import LLMClient
from .entities import canonicalize, entity_id_for
from .ppr import PPREngine

log = logging.getLogger(__name__)

_QE_SYSTEM = (
    "You are an entity-extraction engine. Given a user query, return the "
    "most important noun phrases and named entities the user is asking about. "
    "Return strict JSON. Do not paraphrase or expand acronyms."
)

_QE_USER_TEMPLATE = (
    "Query:\n\"\"\"\n{query}\n\"\"\"\n\n"
    "Output JSON shape:\n"
    "{{\"entities\": [\"...\", \"...\"]}}\n\n"
    "Rules:\n"
    "- Max {max_entities} entities, ordered by importance.\n"
    "- Each entity is a noun phrase, max 60 chars.\n"
    "- Drop stopwords-only phrases. Drop pronouns.\n"
    "- Respond with the JSON object only. No prose."
)


@dataclass
class HippoRAGSearchResult:
    chunks: list[dict]
    seed_entities: list[str]
    ppr_entities_top: list[tuple[str, float]]
    query_entities: list[str]


def extract_query_entities(
    llm_cfg: LLMConfig,
    hipporag_cfg: HippoRAGConfig,
    query: str,
) -> list[str]:
    """Ask the LLM for the key query entities. Returns surface forms."""
    if not query.strip():
        return []
    client = LLMClient(llm_cfg)
    max_n = max(1, int(hipporag_cfg.query_top_entities))
    body = client.chat_json(
        [
            {"role": "system", "content": _QE_SYSTEM},
            {"role": "user", "content": _QE_USER_TEMPLATE.format(query=query, max_entities=max_n)},
        ]
    )
    raw = body.get("entities") if isinstance(body, dict) else None
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw[:max_n]:
        if isinstance(item, str) and item.strip():
            out.append(item.strip()[:60])
    return out


def _load_all_entity_embeddings(
    conn: sqlite3.Connection,
) -> tuple[list[str], np.ndarray, int]:
    rows = conn.execute(
        "SELECT entity_id, dim, vector FROM entity_embeddings"
    ).fetchall()
    if not rows:
        return [], np.zeros((0, 0), dtype=np.float32), 0
    dim = int(rows[0][1])
    ids: list[str] = []
    mat = np.zeros((len(rows), dim), dtype=np.float32)
    for i, (eid, _d, blob) in enumerate(rows):
        ids.append(eid)
        mat[i] = np.asarray(unpack_vector(blob, dim), dtype=np.float32)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    mat /= norms
    return ids, mat, dim


def link_query_entities(
    conn: sqlite3.Connection,
    embedding_cfg: EmbeddingConfig,
    surface_terms: list[str],
    *,
    top_k_per_term: int = 3,
) -> dict[str, float]:
    """Resolve query entities to graph entities.

    Strategy (in order):
    1. exact canonical match wins (weight 1.0)
    2. otherwise cosine-similarity top-K against entity_embeddings
       (weight = max cosine across the term's hits)
    Returns a seed map ``{entity_id: weight}``.
    """
    seeds: dict[str, float] = {}
    if not surface_terms:
        return seeds

    # 1) exact canonical hits
    exact_hits: list[str] = []
    for term in surface_terms:
        canon = canonicalize(term)
        if not canon:
            continue
        eid = entity_id_for(canon)
        row = conn.execute("SELECT entity_id FROM entities WHERE entity_id = ?", (eid,)).fetchone()
        if row:
            seeds[eid] = max(seeds.get(eid, 0.0), 1.0)
            exact_hits.append(term)

    pending = [t for t in surface_terms if t not in exact_hits]
    if not pending or not embedding_cfg or not embedding_cfg.is_configured:
        return seeds

    # 2) embedding-similarity hits for remaining terms
    ids, mat, _dim = _load_all_entity_embeddings(conn)
    if not ids:
        return seeds
    client = EmbeddingClient(embedding_cfg)
    canonicalized = [canonicalize(t) or t for t in pending]
    vectors = client.embed(canonicalized)
    qmat = np.asarray(vectors, dtype=np.float32)
    qnorms = np.linalg.norm(qmat, axis=1, keepdims=True)
    qnorms[qnorms == 0.0] = 1.0
    qmat /= qnorms

    sims = qmat @ mat.T  # [Q, N]
    k = min(top_k_per_term, sims.shape[1])
    for row in sims:
        top = np.argpartition(-row, k - 1)[:k] if k > 0 else []
        for j in top:
            score = float(row[int(j)])
            if score <= 0.0:
                continue
            eid = ids[int(j)]
            seeds[eid] = max(seeds.get(eid, 0.0), score)
    return seeds


def score_chunks(
    conn: sqlite3.Connection,
    ppr_scores: dict[str, float],
    dataset_ids: list[str],
    top_chunks: int,
) -> list[dict]:
    """Aggregate PPR scores into chunk scores via the mentions edges.

    chunk_score = Σ_{e ∈ MENTIONS(chunk)} ppr[e] · log(1 + mention_count)
    """
    if not ppr_scores or not dataset_ids:
        return []
    # Pull mentions for entities with non-trivial PPR mass. Cap to avoid
    # pulling the entire mention table when the seed is huge.
    top_entities = sorted(ppr_scores.items(), key=lambda kv: -kv[1])[:5000]
    if not top_entities:
        return []
    placeholders_e = ",".join("?" * len(top_entities))
    placeholders_d = ",".join("?" * len(dataset_ids))
    params: list = [eid for eid, _ in top_entities] + list(dataset_ids)
    rows = conn.execute(
        f"""
        SELECT cm.chunk_id, cm.entity_id, cm.count, c.dataset_id, c.document_id,
               c.position, c.content, d.name
        FROM chunk_mentions cm
        JOIN chunks c ON c.chunk_id = cm.chunk_id
        JOIN documents d ON d.document_id = c.document_id
        WHERE cm.entity_id IN ({placeholders_e})
          AND c.dataset_id IN ({placeholders_d})
        """,
        params,
    ).fetchall()

    scores: dict[str, dict] = {}
    for chunk_id, entity_id, count, ds_id, doc_id, pos, content, doc_name in rows:
        contribution = ppr_scores.get(entity_id, 0.0) * float(np.log1p(int(count or 1)))
        if contribution <= 0.0:
            continue
        existing = scores.get(chunk_id)
        if existing is None:
            scores[chunk_id] = {
                "chunk_id": chunk_id,
                "dataset_id": ds_id,
                "document_id": doc_id,
                "document_name": doc_name,
                "position": int(pos or 0),
                "content": content,
                "score": contribution,
                "matched_entities": [entity_id],
            }
        else:
            existing["score"] += contribution
            existing["matched_entities"].append(entity_id)

    ranked = sorted(scores.values(), key=lambda d: -d["score"])
    return ranked[: max(1, int(top_chunks))]


def search(
    cfg: Config,
    sqlite_conn: sqlite3.Connection,
    ppr_engine: PPREngine,
    query: str,
    dataset_ids: list[str],
    *,
    top_chunks: int | None = None,
) -> HippoRAGSearchResult:
    """End-to-end HippoRAG search. Caller manages the SQLite connection."""
    if not cfg.llm or not cfg.llm.is_configured:
        raise RuntimeError("LLM endpoint is not configured (set LLM_API_URL / LLM_MODEL)")
    if not cfg.embedding or not cfg.embedding.is_configured:
        raise RuntimeError("Embedding endpoint is not configured")

    query_terms = extract_query_entities(cfg.llm, cfg.hipporag, query)
    seeds = link_query_entities(sqlite_conn, cfg.embedding, query_terms)
    ppr_scores = ppr_engine.run_ppr(sqlite_conn, seeds)
    top_k = top_chunks if top_chunks is not None else cfg.hipporag.top_chunks
    chunks = score_chunks(sqlite_conn, ppr_scores, dataset_ids, top_k)

    top_entities = sorted(ppr_scores.items(), key=lambda kv: -kv[1])[:20]
    return HippoRAGSearchResult(
        chunks=chunks,
        seed_entities=list(seeds.keys()),
        ppr_entities_top=top_entities,
        query_entities=query_terms,
    )
