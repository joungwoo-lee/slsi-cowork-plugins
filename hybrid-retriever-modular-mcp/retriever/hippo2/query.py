"""Query-side Hippo2: extract query entities → link → PPR → score chunks."""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

import numpy as np

from ..config import Config, EmbeddingConfig, Hippo2Config, LLMConfig
from ..embedding_client import EmbeddingClient
from ..graph import unpack_vector
from ..llm_client import LLMClient
from .. import storage
from .entities import canonicalize, entity_id_for
from .ppr import PPREngine, chunk_id_from_passage_node, is_passage_node_id, passage_node_id

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
class Hippo2SearchResult:
    chunks: list[dict]
    seed_entities: list[str]
    seed_passages: list[str]
    ppr_entities_top: list[tuple[str, float]]
    ppr_passages_top: list[tuple[str, float]]
    query_entities: list[str]
    matched_triples: list[dict]
    online_filter: dict


@dataclass(frozen=True)
class QueryTripleMatch:
    triple_id: str
    chunk_id: str
    subject_id: str
    object_id: str
    predicate: str
    score: float


def extract_query_entities(
    llm_cfg: LLMConfig,
    hippo2_cfg: Hippo2Config,
    query: str,
) -> list[str]:
    """Ask the LLM for the key query entities. Returns surface forms."""
    if not query.strip():
        return []
    client = LLMClient(llm_cfg)
    max_n = max(1, int(hippo2_cfg.query_top_entities))
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


def _normalize_matrix(mat: np.ndarray) -> np.ndarray:
    if mat.size == 0:
        return mat
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return mat / norms


def _load_all_fact_embeddings(
    conn: sqlite3.Connection,
    dataset_ids: list[str],
) -> tuple[list[tuple[str, str, str, str, str]], np.ndarray]:
    if not dataset_ids:
        return [], np.zeros((0, 0), dtype=np.float32)
    placeholders = ",".join("?" * len(dataset_ids))
    rows = conn.execute(
        f"""
        SELECT t.subj_id, t.obj_id, t.triple_id, t.chunk_id, t.pred, emb.dim, emb.vector
        FROM fact_embeddings emb
        JOIN triples t ON t.triple_id = emb.triple_id
        WHERE t.dataset_id IN ({placeholders})
        """,
        dataset_ids,
    ).fetchall()
    if not rows:
        return [], np.zeros((0, 0), dtype=np.float32)
    dim = int(rows[0][5])
    facts: list[tuple[str, str, str, str, str]] = []
    mat = np.zeros((len(rows), dim), dtype=np.float32)
    for i, (subj_id, obj_id, triple_id, chunk_id, pred, _dim, blob) in enumerate(rows):
        facts.append((subj_id, obj_id, triple_id, chunk_id, pred or ""))
        mat[i] = np.asarray(unpack_vector(blob, dim), dtype=np.float32)
    return facts, _normalize_matrix(mat)


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


def link_query_facts(
    conn: sqlite3.Connection,
    embedding_cfg: EmbeddingConfig,
    query: str,
    dataset_ids: list[str],
    *,
    top_k: int,
) -> dict[str, float]:
    """Retrieve fact embeddings and turn their subject/object entities into seeds."""
    matches = link_query_triples(conn, embedding_cfg, query, dataset_ids, top_k=top_k)
    seeds: dict[str, float] = {}
    for match in matches:
        seeds[match.subject_id] = max(seeds.get(match.subject_id, 0.0), match.score)
        seeds[match.object_id] = max(seeds.get(match.object_id, 0.0), match.score)
    return seeds


def link_query_triples(
    conn: sqlite3.Connection,
    embedding_cfg: EmbeddingConfig,
    query: str,
    dataset_ids: list[str],
    *,
    top_k: int,
) -> list[QueryTripleMatch]:
    """Retrieve triples by whole-query embedding similarity.

    This is the Hippo2 Query-to-Triple alignment stage: the query vector is
    compared directly with OpenIE triple embeddings, and each local hit seeds
    both its endpoint entities and the passage node where the triple appears.
    """
    if not query.strip() or not embedding_cfg or not embedding_cfg.is_configured:
        return []
    facts, mat = _load_all_fact_embeddings(conn, dataset_ids)
    if not facts:
        return []
    [vector] = EmbeddingClient(embedding_cfg).embed([query])
    q = np.asarray([vector], dtype=np.float32)
    q = _normalize_matrix(q)
    sims = (q @ mat.T).ravel()
    k = min(max(1, int(top_k)), sims.shape[0])
    top = np.argpartition(-sims, k - 1)[:k]
    matches: list[QueryTripleMatch] = []
    for idx in top:
        score = float(sims[int(idx)])
        if score <= 0.0:
            continue
        subj_id, obj_id, triple_id, chunk_id, pred = facts[int(idx)]
        matches.append(QueryTripleMatch(
            triple_id=triple_id,
            chunk_id=chunk_id,
            subject_id=subj_id,
            object_id=obj_id,
            predicate=pred,
            score=score,
        ))
    matches.sort(key=lambda item: -item.score)
    return matches


def dense_passage_chunks(
    cfg: Config,
    conn: sqlite3.Connection,
    query: str,
    dataset_ids: list[str],
    top_chunks: int,
) -> list[dict]:
    if not cfg.embedding or not cfg.embedding.is_configured or not query.strip():
        return []
    [vector] = EmbeddingClient(cfg.embedding).embed([query])
    qdrant = storage.open_qdrant(cfg)
    storage.ensure_collection(qdrant, cfg)
    rows = storage.vector_search(qdrant, cfg, vector, dataset_ids, max(1, int(top_chunks)))
    chunks = storage.fetch_chunks(conn, [row["chunk_id"] for row in rows])
    out: list[dict] = []
    for row in rows:
        chunk = chunks.get(row["chunk_id"])
        if not chunk:
            continue
        out.append({
            "chunk_id": chunk["chunk_id"],
            "dataset_id": chunk["dataset_id"],
            "document_id": chunk["document_id"],
            "document_name": chunk["document_name"],
            "position": chunk["position"],
            "content": chunk["content"],
            "score": max(0.0, min(1.0, (float(row["score"]) + 1.0) / 2.0)),
            "matched_entities": [],
        })
    return out


def score_chunks(
    conn: sqlite3.Connection,
    ppr_scores: dict[str, float],
    dataset_ids: list[str],
    top_chunks: int,
) -> list[dict]:
    """Aggregate PPR scores into chunks.

    Passage nodes contribute directly. Entity nodes also contribute through
    ``chunk_mentions`` so older entity-only paths remain useful:

    ``chunk_score = ppr[passage] + Σ ppr[entity] · log(1 + mention_count)``
    """
    if not ppr_scores or not dataset_ids:
        return []

    placeholders_d = ",".join("?" * len(dataset_ids))
    passage_scores = {
        chunk_id_from_passage_node(node_id): score
        for node_id, score in ppr_scores.items()
        if is_passage_node_id(node_id) and score > 0.0
    }
    scores: dict[str, dict] = {}
    if passage_scores:
        placeholders_p = ",".join("?" * len(passage_scores))
        rows = conn.execute(
            f"""
            SELECT c.chunk_id, c.dataset_id, c.document_id, c.position, c.content, d.name
            FROM chunks c
            JOIN documents d ON d.document_id = c.document_id
            WHERE c.chunk_id IN ({placeholders_p})
              AND c.dataset_id IN ({placeholders_d})
            """,
            list(passage_scores.keys()) + list(dataset_ids),
        ).fetchall()
        for chunk_id, ds_id, doc_id, pos, content, doc_name in rows:
            score = float(passage_scores.get(chunk_id, 0.0))
            if score <= 0.0:
                continue
            scores[chunk_id] = {
                "chunk_id": chunk_id,
                "dataset_id": ds_id,
                "document_id": doc_id,
                "document_name": doc_name,
                "position": int(pos or 0),
                "content": content,
                "score": score,
                "passage_node_score": score,
                "entity_ppr_score": 0.0,
                "matched_entities": [],
            }

    entity_scores = {
        node_id: score
        for node_id, score in ppr_scores.items()
        if not is_passage_node_id(node_id) and score > 0.0
    }
    # Pull mentions for entities with non-trivial PPR mass. Cap to avoid
    # pulling the entire mention table when the seed is huge.
    top_entities = sorted(entity_scores.items(), key=lambda kv: -kv[1])[:5000]
    if not top_entities:
        ranked = sorted(scores.values(), key=lambda d: -d["score"])
        return ranked[: max(1, int(top_chunks))]
    placeholders_e = ",".join("?" * len(top_entities))
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

    for chunk_id, entity_id, count, ds_id, doc_id, pos, content, doc_name in rows:
        contribution = entity_scores.get(entity_id, 0.0) * float(np.log1p(int(count or 1)))
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
                "passage_node_score": 0.0,
                "entity_ppr_score": contribution,
                "matched_entities": [entity_id],
            }
        else:
            existing["score"] += contribution
            existing["entity_ppr_score"] = float(existing.get("entity_ppr_score", 0.0)) + contribution
            existing["matched_entities"].append(entity_id)

    ranked = sorted(scores.values(), key=lambda d: -d["score"])
    return ranked[: max(1, int(top_chunks))]


_FILTER_SYSTEM = (
    "You are a recognition-memory filter for a retrieval engine. Given a query "
    "and candidate passages, keep only passages that can plausibly help answer "
    "the query. Return strict JSON only."
)

_FILTER_USER_TEMPLATE = (
    "Query:\n\"\"\"\n{query}\n\"\"\"\n\n"
    "Candidates JSON:\n{candidates}\n\n"
    "Return JSON shape:\n"
    "{{\"keep_chunk_ids\": [\"chunk_id\", \"...\"]}}\n\n"
    "Rules:\n"
    "- Keep passages with direct facts, necessary context, or strong associative clues.\n"
    "- Drop generic or off-topic passages.\n"
    "- Keep at least {min_keep} passage(s) if any candidate is even weakly relevant.\n"
    "- Do not invent chunk ids. Return JSON only."
)


def online_filter_chunks(
    llm_cfg: LLMConfig,
    query: str,
    chunks: list[dict],
    *,
    max_candidates: int,
    min_keep: int,
) -> tuple[list[dict], dict]:
    if not chunks or max_candidates <= 0:
        return chunks, {"enabled": False, "reason": "no_candidates"}
    candidates = chunks[:max_candidates]
    import json

    payload = [
        {
            "chunk_id": c["chunk_id"],
            "score": round(float(c.get("score") or 0.0), 6),
            "matched_entities": c.get("matched_entities", []),
            "text": (c.get("content") or "")[:1200],
        }
        for c in candidates
    ]
    try:
        body = LLMClient(llm_cfg).chat_json([
            {"role": "system", "content": _FILTER_SYSTEM},
            {
                "role": "user",
                "content": _FILTER_USER_TEMPLATE.format(
                    query=query,
                    candidates=json.dumps(payload, ensure_ascii=False),
                    min_keep=max(1, int(min_keep)),
                ),
            },
        ])
    except Exception as exc:  # noqa: BLE001
        log.warning("Hippo2 online filter failed: %s", exc)
        return chunks, {"enabled": True, "error": str(exc), "kept": len(chunks), "dropped": 0}

    raw_keep = body.get("keep_chunk_ids") if isinstance(body, dict) else None
    if not isinstance(raw_keep, list):
        return chunks, {"enabled": True, "error": "invalid_filter_response", "kept": len(chunks), "dropped": 0}

    keep_ids = {str(item) for item in raw_keep if isinstance(item, str)}
    if not keep_ids:
        keep_ids = {c["chunk_id"] for c in candidates[: max(1, int(min_keep))]}
    kept_candidates = [dict(c, online_filter="kept") for c in candidates if c["chunk_id"] in keep_ids]
    if len(kept_candidates) < max(1, int(min_keep)):
        kept_ids = {c["chunk_id"] for c in kept_candidates}
        for c in candidates:
            if c["chunk_id"] not in kept_ids:
                kept_candidates.append(dict(c, online_filter="fallback_keep"))
                kept_ids.add(c["chunk_id"])
            if len(kept_candidates) >= max(1, int(min_keep)):
                break
    remainder = chunks[max_candidates:]
    filtered = kept_candidates + remainder
    return filtered, {
        "enabled": True,
        "candidates": len(candidates),
        "kept": len(kept_candidates),
        "dropped": max(0, len(candidates) - len(kept_candidates)),
    }


def search(
    cfg: Config,
    sqlite_conn: sqlite3.Connection,
    ppr_engine: PPREngine,
    query: str,
    dataset_ids: list[str],
    *,
    top_chunks: int | None = None,
) -> Hippo2SearchResult:
    """End-to-end Hippo2 search. Caller manages the SQLite connection."""
    if not cfg.llm or not cfg.llm.is_configured:
        raise RuntimeError("LLM endpoint is not configured (set LLM_API_URL / LLM_MODEL)")
    if not cfg.embedding or not cfg.embedding.is_configured:
        raise RuntimeError("Embedding endpoint is not configured")

    top_k = top_chunks if top_chunks is not None else cfg.hippo2.top_chunks
    candidate_k = max(top_k, int(cfg.hippo2.online_filter_candidates))
    query_terms = extract_query_entities(cfg.llm, cfg.hippo2, query)
    seeds = link_query_entities(sqlite_conn, cfg.embedding, query_terms)
    triple_matches = link_query_triples(
        sqlite_conn,
        cfg.embedding,
        query,
        dataset_ids,
        top_k=max(1, int(cfg.hippo2.linking_top_k)),
    )
    for match in triple_matches:
        seeds[match.subject_id] = max(seeds.get(match.subject_id, 0.0), match.score)
        seeds[match.object_id] = max(seeds.get(match.object_id, 0.0), match.score)
        pnode = passage_node_id(match.chunk_id)
        seeds[pnode] = max(seeds.get(pnode, 0.0), match.score)

    dense_chunks = dense_passage_chunks(cfg, sqlite_conn, query, dataset_ids, candidate_k)
    for chunk in dense_chunks:
        pnode = passage_node_id(chunk["chunk_id"])
        passage_score = float(chunk["score"]) * float(cfg.hippo2.passage_node_weight)
        seeds[pnode] = max(seeds.get(pnode, 0.0), passage_score)

    ppr_scores = ppr_engine.run_ppr(sqlite_conn, seeds)
    chunks = score_chunks(sqlite_conn, ppr_scores, dataset_ids, candidate_k)
    online_filter = {"enabled": False}
    if cfg.hippo2.online_filter_enabled:
        chunks, online_filter = online_filter_chunks(
            cfg.llm,
            query,
            chunks,
            max_candidates=max(1, int(cfg.hippo2.online_filter_candidates)),
            min_keep=max(1, int(cfg.hippo2.online_filter_min_keep)),
        )
    chunks = sorted(chunks, key=lambda item: -float(item["score"]))[:top_k]

    top_entities = sorted(
        ((node_id, score) for node_id, score in ppr_scores.items() if not is_passage_node_id(node_id)),
        key=lambda kv: -kv[1],
    )[:20]
    top_passages = sorted(
        ((chunk_id_from_passage_node(node_id), score) for node_id, score in ppr_scores.items() if is_passage_node_id(node_id)),
        key=lambda kv: -kv[1],
    )[:20]
    return Hippo2SearchResult(
        chunks=chunks,
        seed_entities=[node_id for node_id in seeds if not is_passage_node_id(node_id)],
        seed_passages=[chunk_id_from_passage_node(node_id) for node_id in seeds if is_passage_node_id(node_id)],
        ppr_entities_top=top_entities,
        ppr_passages_top=top_passages,
        query_entities=query_terms,
        matched_triples=[
            {
                "triple_id": match.triple_id,
                "chunk_id": match.chunk_id,
                "subject_id": match.subject_id,
                "object_id": match.object_id,
                "predicate": match.predicate,
                "score": match.score,
            }
            for match in triple_matches
        ],
        online_filter=online_filter,
    )
