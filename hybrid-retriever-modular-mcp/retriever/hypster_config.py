"""Hypster configuration spaces for indexing and retrieval.

Following the gilad-rubin/modular-rag pattern, every tunable knob is declared
once here as part of a typed ``hp.*`` call. ``retriever.api`` snapshots the
current process ``Config`` defaults into these spaces, then overrides with the
per-call kwargs forwarded from the MCP handlers. The returned ``dict`` is the
single source of truth handed to pipeline builders.

The MCP server stays compatible with hypster-free environments: if
``import hypster`` fails (e.g. dependency install still running), callers fall
back to merging defaults + overrides by hand via ``compose_defaults``.
"""
from __future__ import annotations

from typing import Any

from .config import Config


def compose_defaults(cfg: Config) -> dict[str, dict[str, Any]]:
    """Return indexing/retrieval defaults derived from process Config.

    Used as fallback when Hypster is unavailable and as the seed values
    passed into the Hypster instantiation below.
    """
    return {
        "indexing": {
            "use_hierarchical": "false",
            "chunk_chars": cfg.ingest.chunk_chars,
            "chunk_overlap": cfg.ingest.chunk_overlap,
            "parent_chunk_chars": cfg.ingest.parent_chunk_chars,
            "parent_chunk_overlap": cfg.ingest.parent_chunk_overlap,
            "child_chunk_chars": cfg.ingest.child_chunk_chars,
            "child_chunk_overlap": cfg.ingest.child_chunk_overlap,
            "max_file_chars": cfg.ingest.max_file_chars,
            "skip_embedding": False,
        },
        "retrieval": {
            "fusion": cfg.search.fusion or "linear",
            "hybrid_alpha": cfg.search.hybrid_alpha,
            "rrf_k": cfg.search.rrf_k,
            "parent_chunk_replace": cfg.search.parent_chunk_replace,
            "keyword": True,
            "top_n": 12,
            "top_k": 200,
            "use_reranker": False,
            "reranker_model": "BAAI/bge-reranker-v2-m3",
            "rerank_top_n": 12,
        },
    }


def indexing_config(hp) -> dict[str, Any]:
    """Hypster indexing space. Returns chunking / embedding knobs."""
    use_hierarchical = hp.select(["false", "true", "full"], default="false", name="use_hierarchical")
    chunk_chars = hp.int(512, name="chunk_chars", min=1)
    chunk_overlap = hp.int(50, name="chunk_overlap", min=0)
    parent_chunk_chars = hp.int(1024, name="parent_chunk_chars", min=1)
    parent_chunk_overlap = hp.int(100, name="parent_chunk_overlap", min=0)
    child_chunk_chars = hp.int(256, name="child_chunk_chars", min=1)
    child_chunk_overlap = hp.int(50, name="child_chunk_overlap", min=0)
    max_file_chars = hp.int(2_000_000, name="max_file_chars", min=1)
    skip_embedding = hp.bool(False, name="skip_embedding")
    return hp.collect(locals())


def retrieval_config(hp) -> dict[str, Any]:
    """Hypster retrieval space. Returns fusion / weighting / paging knobs."""
    fusion = hp.select(["linear", "rrf"], default="linear", name="fusion")
    hybrid_alpha = hp.float(0.5, name="hybrid_alpha", min=0.0, max=1.0)
    rrf_k = hp.int(60, name="rrf_k", min=1)
    parent_chunk_replace = hp.bool(True, name="parent_chunk_replace")
    keyword = hp.bool(True, name="keyword")
    top_n = hp.int(12, name="top_n", min=1, max=50)
    top_k = hp.int(200, name="top_k", min=1, max=500)
    use_reranker = hp.bool(False, name="use_reranker")
    reranker_model = hp.text("BAAI/bge-reranker-v2-m3", name="reranker_model")
    rerank_top_n = hp.int(12, name="rerank_top_n", min=1, max=200)
    return hp.collect(locals())


def select_indexing(cfg: Config, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve indexing knobs, preferring Hypster when available."""
    defaults = compose_defaults(cfg)["indexing"]
    merged = {**defaults, **{k: v for k, v in (overrides or {}).items() if v is not None}}
    return _try_instantiate(indexing_config, merged) or merged


def select_retrieval(cfg: Config, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve retrieval knobs, preferring Hypster when available."""
    defaults = compose_defaults(cfg)["retrieval"]
    merged = {**defaults, **{k: v for k, v in (overrides or {}).items() if v is not None}}
    return _try_instantiate(retrieval_config, merged) or merged


def _try_instantiate(func, values: dict[str, Any]) -> dict[str, Any] | None:
    try:
        from hypster import instantiate
    except Exception:
        return None
    try:
        return instantiate(func, values=values, on_unknown="ignore")
    except Exception:
        return None
