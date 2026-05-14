"""High-level facade: signatures match the legacy ``scripts.{ingest,search}`` API
plus an optional ``pipeline`` kwarg for selecting a named pipeline profile.

MCP handlers stay simple -- they forward kwargs as-is and the facade resolves
the profile, merges Hypster overrides, and runs the right Haystack pipeline.
"""
from __future__ import annotations

from typing import Any

from .config import Config
from .hypster_config import select_indexing, select_retrieval
from .pipelines import profiles, run_indexing, run_retrieval


def upload_document(
    cfg: Config,
    dataset_id: str,
    file_path: str,
    *,
    pipeline: str = "default",
    skip_embedding: bool = False,
    use_hierarchical: str | bool | None = None,
    metadata: dict | None = None,
) -> dict:
    """Public ingest entrypoint -- forwards to the indexing pipeline.

    ``pipeline`` picks a named ``PipelineProfile`` from the registry. The
    profile's ``indexing_overrides`` are merged with any per-call kwargs
    (``skip_embedding``, ``use_hierarchical``), so a profile can either set
    defaults the caller can still override (e.g. ``skip_embedding=True`` as a
    default) or force values the caller cannot change.
    """
    profiles.sync_with_disk(cfg)
    profile = profiles.get(pipeline)
    overrides: dict[str, Any] = {**profile.indexing_overrides}
    if skip_embedding:  # caller-provided True wins; profile False stays False unless caller bumps it
        overrides["skip_embedding"] = True
    if use_hierarchical is not None:
        overrides["use_hierarchical"] = (
            "full" if str(use_hierarchical).lower() == "full"
            else ("true" if str(use_hierarchical).lower() == "true" else "false")
        )
    opts = select_indexing(cfg, overrides)
    return run_indexing(
        cfg,
        dataset_id,
        file_path,
        indexing_opts=opts,
        metadata=metadata,
        builder=profile.build_indexing,
    )


def hybrid_search(
    cfg: Config,
    query: str,
    dataset_ids: list[str],
    *,
    pipeline: str = "default",
    top: int = 12,
    top_k: int = 200,
    vector_similarity_weight: float | None = None,
    keyword: bool = True,
    fusion: str | None = None,
    parent_chunk_replace: bool | None = None,
    metadata_condition: dict | None = None,
) -> dict:
    """Public search entrypoint -- forwards to the retrieval pipeline.

    ``pipeline`` picks a named profile. Its ``retrieval_overrides`` seed the
    Hypster space; its ``search_kwargs`` then *force* any per-call kwargs
    (e.g. ``vector_similarity_weight``) the profile wants pinned. This is
    how ``keyword_only`` guarantees no vector branch even if a caller passes
    ``vector_similarity_weight=0.7``.
    """
    profiles.sync_with_disk(cfg)
    profile = profiles.get(pipeline)
    overrides: dict[str, Any] = {
        **profile.retrieval_overrides,
        "top_n": int(top),
        "top_k": int(top_k),
        "keyword": bool(keyword),
    }
    if fusion is not None:
        overrides["fusion"] = fusion
    opts = select_retrieval(cfg, overrides)

    # Profile-forced kwargs win over caller-provided ones.
    forced = profile.search_kwargs
    if "vector_similarity_weight" in forced:
        vector_similarity_weight = forced["vector_similarity_weight"]
    effective_fusion = forced.get("fusion", fusion)
    effective_parent = forced.get("parent_chunk_replace", parent_chunk_replace)

    return run_retrieval(
        cfg,
        query,
        dataset_ids,
        retrieval_opts=opts,
        vector_similarity_weight=vector_similarity_weight,
        fusion=effective_fusion,
        parent_chunk_replace=effective_parent,
        metadata_condition=metadata_condition,
        builder=profile.build_retrieval,
    )
