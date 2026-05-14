"""High-level facade: signatures match the legacy ``scripts.{ingest,search}`` API.

MCP handlers stay unchanged -- they import ``upload_document`` and
``hybrid_search`` and call them with the same kwargs. Internally we resolve
the per-call Hypster configuration and run the corresponding Haystack pipeline.
"""
from __future__ import annotations

from typing import Any

from .config import Config
from .hypster_config import select_indexing, select_retrieval
from .pipelines import run_indexing, run_retrieval


def upload_document(
    cfg: Config,
    dataset_id: str,
    file_path: str,
    *,
    skip_embedding: bool = False,
    use_hierarchical: str | bool | None = None,
    metadata: dict | None = None,
) -> dict:
    """Public ingest entrypoint -- forwards to the indexing pipeline.

    Accepts ``use_hierarchical`` in any of the legacy forms (``"true"``,
    ``"false"``, ``"full"``, ``bool``, ``None``); the splitter normalises
    them.
    """
    overrides: dict[str, Any] = {"skip_embedding": bool(skip_embedding)}
    if use_hierarchical is not None:
        overrides["use_hierarchical"] = (
            "full" if str(use_hierarchical).lower() == "full"
            else ("true" if str(use_hierarchical).lower() == "true" else "false")
        )
    opts = select_indexing(cfg, overrides)
    return run_indexing(cfg, dataset_id, file_path, indexing_opts=opts, metadata=metadata)


def hybrid_search(
    cfg: Config,
    query: str,
    dataset_ids: list[str],
    *,
    top: int = 12,
    top_k: int = 200,
    vector_similarity_weight: float | None = None,
    keyword: bool = True,
    fusion: str | None = None,
    parent_chunk_replace: bool | None = None,
    metadata_condition: dict | None = None,
) -> dict:
    """Public search entrypoint -- forwards to the retrieval pipeline."""
    overrides: dict[str, Any] = {
        "top_n": int(top),
        "top_k": int(top_k),
        "keyword": bool(keyword),
    }
    if fusion is not None:
        overrides["fusion"] = fusion
    opts = select_retrieval(cfg, overrides)
    return run_retrieval(
        cfg,
        query,
        dataset_ids,
        retrieval_opts=opts,
        vector_similarity_weight=vector_similarity_weight,
        fusion=fusion,
        parent_chunk_replace=parent_chunk_replace,
        metadata_condition=metadata_condition,
    )
