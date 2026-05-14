"""Retrieval pipeline: query -> keyword + semantic -> fuse -> parent-replace.

Returns the same response shape as the legacy ``scripts.search.hybrid_search``
so handlers and downstream consumers (Claude, MCP clients) need not change.
"""
from __future__ import annotations

from typing import Any

from haystack import Pipeline

from ..components import (
    Fts5Retriever,
    HttpTextEmbedder,
    HybridJoiner,
    LocalQdrantRetriever,
    ParentChunkReplacer,
)
from ..config import Config


def build_retrieval_pipeline(cfg: Config) -> Pipeline:
    """Build a Haystack Pipeline that fuses keyword + semantic retrieval."""
    pipeline = Pipeline()
    pipeline.add_component("query_embedder", HttpTextEmbedder(cfg.embedding))
    pipeline.add_component("fts5", Fts5Retriever(cfg))
    pipeline.add_component("vector", LocalQdrantRetriever(cfg))
    pipeline.add_component("joiner", HybridJoiner())
    pipeline.add_component("parent", ParentChunkReplacer())
    pipeline.connect("query_embedder.embedding", "vector.embedding")
    pipeline.connect("fts5.documents", "joiner.keyword_documents")
    pipeline.connect("vector.documents", "joiner.semantic_documents")
    pipeline.connect("joiner.documents", "parent.documents")
    return pipeline


def run_retrieval(
    cfg: Config,
    query: str,
    dataset_ids: list[str],
    *,
    retrieval_opts: dict[str, Any],
    vector_similarity_weight: float | None = None,
    fusion: str | None = None,
    parent_chunk_replace: bool | None = None,
    metadata_condition: dict | None = None,
    builder=None,
) -> dict:
    """Execute the retrieval pipeline and assemble the legacy response shape."""
    pipeline = (builder or build_retrieval_pipeline)(cfg)
    weight = (
        float(vector_similarity_weight)
        if vector_similarity_weight is not None
        else float(retrieval_opts["hybrid_alpha"])
    )
    if not (cfg.embedding.api_url and cfg.embedding.dim > 0):
        weight = 0.0
    fusion_mode = (fusion or retrieval_opts["fusion"] or "linear").lower()
    replace_parent = (
        bool(parent_chunk_replace)
        if parent_chunk_replace is not None
        else bool(retrieval_opts["parent_chunk_replace"])
    )
    top_n = int(retrieval_opts["top_n"])
    top_k = int(retrieval_opts["top_k"])

    result = pipeline.run(
        {
            "query_embedder": {"text": query if weight > 0.0 else ""},
            "fts5": {
                "query": query,
                "dataset_ids": dataset_ids,
                "top_k": top_k,
                "enabled": bool(retrieval_opts.get("keyword", True)),
            },
            "vector": {"dataset_ids": dataset_ids, "top_k": top_k},
            "joiner": {
                "fusion": fusion_mode,
                "vector_weight": weight,
                "rrf_k": int(retrieval_opts["rrf_k"]),
                "metadata_condition": metadata_condition,
            },
            "parent": {"enabled": replace_parent},
        },
        include_outputs_from={"parent"},
    )
    docs = result["parent"]["documents"]
    items = [_doc_to_item(d, replace_parent) for d in docs[:top_n]]
    return {"total": len(docs), "items": items}


def _doc_to_item(doc, parent_replace: bool) -> dict[str, Any]:
    meta = doc.meta or {}
    child_content = meta.get("child_content") or doc.content or ""
    parent_content = meta.get("parent_content", "") or ""
    is_hier = bool(meta.get("is_hierarchical"))
    content = doc.content or child_content
    return {
        "id": doc.id,
        "chunk_id": doc.id,
        "dataset_id": meta.get("dataset_id"),
        "document_id": meta.get("document_id"),
        "document_name": meta.get("document_name"),
        "position": int(meta.get("position", 0)),
        "content": content if (parent_replace and is_hier) else child_content,
        "child_content": child_content,
        "parent_content": parent_content,
        "parent_id": int(meta.get("parent_id", 0)),
        "child_id": int(meta.get("child_id", meta.get("position", 0))),
        "is_hierarchical": is_hier,
        "is_contextual": bool(meta.get("is_contextual")),
        "metadata": meta.get("metadata") or {},
        "similarity": float(doc.score or 0.0),
        "vector_similarity": float(meta.get("vector_similarity", 0.0)),
        "term_similarity": float(meta.get("term_similarity", 0.0)),
    }
