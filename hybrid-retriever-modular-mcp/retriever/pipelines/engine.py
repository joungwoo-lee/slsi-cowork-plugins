"""Pipeline registry, JSON topology loader, and execution engine.

Profile registration
--------------------
Built-in profiles ship as ``registry.json`` next to this file. User-defined
profiles can be added at runtime by writing to ``$RETRIEVER_DATA_ROOT/pipelines.json``
and calling :func:`sync_profiles_with_disk` — the MCP ``save_pipeline`` tool
does this automatically.

Pipeline topologies (the actual component graph) live in ``*_indexing.json``
and ``*_retrieval.json`` next to this file. Profiles can override which
topology to load via ``indexing_topology`` / ``retrieval_topology``.
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from haystack import Pipeline

from .. import storage  # noqa: F401  (importing for side-effects? keep explicit below)
from ..config import Config
from .node_topology import is_node_centric, to_haystack_dict

logger = logging.getLogger(__name__)

PIPELINES_DIR = Path(__file__).parent
REGISTRY_PATH = PIPELINES_DIR / "registry.json"

DEFAULT_UNIFIED_TOPOLOGY = "default_unified.json"


# --- Profile registry -------------------------------------------------------

@dataclass(frozen=True)
class PipelineProfile:
    name: str
    description: str = ""
    indexing_overrides: dict[str, Any] = field(default_factory=dict)
    retrieval_overrides: dict[str, Any] = field(default_factory=dict)
    search_kwargs: dict[str, Any] = field(default_factory=dict)
    indexing_topology: Optional[str] = None
    retrieval_topology: Optional[str] = None
    unified_topology: Optional[str] = None


_REGISTRY: dict[str, PipelineProfile] = {}


def register(profile: PipelineProfile) -> None:
    _REGISTRY[profile.name] = profile


def get_profile(name: str) -> PipelineProfile:
    if name in _REGISTRY:
        return _REGISTRY[name]
    if "default" in _REGISTRY:
        return _REGISTRY["default"]
    raise KeyError(f"no pipeline profile named '{name}' and no default registered")


def list_profile_names() -> list[str]:
    return list(_REGISTRY.keys())


def describe_profiles() -> list[dict[str, Any]]:
    return [
        {
            "name": p.name,
            "description": p.description,
            "indexing_overrides": p.indexing_overrides,
            "retrieval_overrides": p.retrieval_overrides,
            "search_kwargs": p.search_kwargs,
            "unified_topology": p.unified_topology,
        }
        for p in _REGISTRY.values()
    ]


def _read_topology_description(topology_file: str | None) -> str:
    """Read ``metadata.description`` from a topology JSON file.

    Returns an empty string if the file or field is missing — callers fall
    back to the profile-level description in that case.
    """
    if not topology_file:
        return ""
    path = PIPELINES_DIR / topology_file
    if not path.is_file():
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return ""
    meta = raw.get("metadata") if isinstance(raw, dict) else None
    desc = meta.get("description") if isinstance(meta, dict) else None
    return desc if isinstance(desc, str) else ""


def _load_profile_dict(data: dict[str, Any]) -> None:
    for name, item in data.items():
        if not isinstance(item, dict):
            logger.warning("skipping malformed pipeline profile %r", name)
            continue
        item = dict(item)
        if not item.get("description"):
            # Description lives in each topology's metadata; the profile entry
            # only carries it in-memory.
            topology_file = (
                item.get("unified_topology")
                or item.get("retrieval_topology")
                or item.get("indexing_topology")
            )
            item["description"] = _read_topology_description(topology_file)
        try:
            register(PipelineProfile(name=name, **item))
        except TypeError as exc:
            logger.warning("skipping profile %r: %s", name, exc)


def load_builtin_registry() -> None:
    if not REGISTRY_PATH.exists():
        return
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("failed to load built-in registry %s: %s", REGISTRY_PATH, exc)
        return
    if isinstance(data, dict):
        _load_profile_dict(data)


def sync_profiles_with_disk(cfg: Config) -> None:
    """Merge user-defined profiles from ``$DATA_ROOT/pipelines.json``."""
    json_path = cfg.data_root / "pipelines.json"
    if not json_path.exists():
        return
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("failed to load user profiles from %s: %s", json_path, exc)
        return
    if isinstance(data, dict):
        _load_profile_dict(data)


# --- Topology loading + runtime injection -----------------------------------

def _load_pipeline(topology_file: str) -> Pipeline:
    topology_path = PIPELINES_DIR / topology_file
    if not topology_path.is_file():
        raise FileNotFoundError(f"pipeline topology not found: {topology_path}")
    with open(topology_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    if is_node_centric(raw):
        raw = to_haystack_dict(raw)
    return Pipeline.from_dict(raw)


def _iter_components(pipeline: Pipeline):
    for name, node in pipeline.graph.nodes.items():
        instance = node.get("instance")
        if instance is not None:
            yield name, instance


def _inject_indexing_runtime(pipeline: Pipeline, cfg: Config, opts: dict[str, Any]) -> None:
    """Apply cfg + per-call options to the components of an indexing pipeline.

    The JSON topology cannot embed runtime values (data_root, api_key, ...)
    so each instance is updated in place before pipeline.run().
    """
    emb = cfg.embedding
    for name, inst in _iter_components(pipeline):
        if hasattr(inst, "max_chars") and "max_file_chars" in opts:
            inst.max_chars = int(opts["max_file_chars"])
        if name == "splitter":
            for attr in ("chunk_chars", "chunk_overlap",
                         "parent_chunk_chars", "parent_chunk_overlap",
                         "child_chunk_chars", "child_chunk_overlap"):
                if attr in opts and hasattr(inst, attr):
                    setattr(inst, attr, int(opts[attr]))
        if name == "embedder" and hasattr(inst, "api_url"):
            inst.api_url = emb.api_url if emb else ""
            inst.api_key = emb.api_key if emb else ""
            inst.model = emb.model if emb else ""
            inst.dim = emb.dim if emb else 0
            if emb:
                inst.x_dep_ticket = emb.x_dep_ticket
                inst.x_system_name = emb.x_system_name
                inst.batch_size = emb.batch_size
                inst.timeout_sec = emb.timeout_sec
                inst.verify_ssl = emb.verify_ssl
        if name in ("writer", "qdrant_writer", "vector") and hasattr(inst, "data_root"):
            inst.data_root = str(cfg.data_root)
            if hasattr(inst, "collection"):
                inst.collection = cfg.qdrant.collection


def _inject_retrieval_runtime(pipeline: Pipeline, cfg: Config) -> None:
    emb = cfg.embedding
    for name, inst in _iter_components(pipeline):
        if name == "query_embedder" and hasattr(inst, "api_url"):
            inst.api_url = emb.api_url if emb else ""
            inst.api_key = emb.api_key if emb else ""
            inst.model = emb.model if emb else ""
            inst.dim = emb.dim if emb else 0
            if emb:
                inst.x_dep_ticket = emb.x_dep_ticket
                inst.x_system_name = emb.x_system_name
                inst.batch_size = emb.batch_size
                inst.timeout_sec = emb.timeout_sec
                inst.verify_ssl = emb.verify_ssl
        if name in ("fts5", "graph", "vector") and hasattr(inst, "data_root"):
            inst.data_root = str(cfg.data_root)
            if name == "vector" and hasattr(inst, "collection"):
                inst.collection = cfg.qdrant.collection


# --- Indexing ---------------------------------------------------------------

def _stage_source(path: Path, cfg: Config, dataset_id: str, doc_id: str) -> tuple[Path, Path]:
    doc_dir = cfg.document_dir(dataset_id, doc_id)
    doc_dir.mkdir(parents=True, exist_ok=True)
    stored_source = cfg.source_path(dataset_id, doc_id, path.name)
    stored_content = cfg.content_path(dataset_id, doc_id)
    if path.is_dir():
        if stored_source.exists():
            shutil.rmtree(stored_source, ignore_errors=True)
        shutil.copytree(path, stored_source)
    else:
        shutil.copy2(path, stored_source)
    return stored_source, stored_content


def _combined_metadata(loader_out: dict, metadata: dict | None) -> dict:
    loader_meta = loader_out.get("email_metadata")
    if not loader_meta:
        raws = loader_out.get("raw_emails")
        if isinstance(raws, list) and len(raws) == 1:
            loader_meta = raws[0]
    return {**(loader_meta or {}), **(metadata or {})}


def _decorate_documents(documents, stored_source: Path, stored_content: Path,
                        path: Path, loader_out: dict, has_vector: bool,
                        combined_metadata: dict) -> None:
    size_bytes = int(
        loader_out.get("size_bytes")
        or (path.stat().st_size if path.is_file() else 0)
    )
    base = {
        "document_name": path.name,
        "source_path": str(stored_source),
        "content_path": str(stored_content),
        "size_bytes": size_bytes,
        "has_vector": has_vector,
        "document_metadata": combined_metadata,
    }
    for doc in documents:
        doc.meta.update(base)
        chunk_meta = doc.meta.get("metadata") or {}
        combined = {**combined_metadata, **chunk_meta}
        doc.meta["metadata"] = combined
        for k, v in combined.items():
            if k not in doc.meta:
                doc.meta[k] = v


def _resolve_text(loader_out: dict) -> str:
    text = loader_out.get("text")
    if text is not None:
        return text
    raws = loader_out.get("raw_emails")
    if isinstance(raws, list):
        return f"Multi-email: {len(raws)}"
    return ""


def run_indexing(
    cfg: Config,
    dataset_id: str,
    file_path: str,
    indexing_opts: dict[str, Any],
    metadata: dict | None = None,
    profile: PipelineProfile | None = None,
) -> dict:
    """Orchestrate the indexing pipeline for one file or email directory."""
    path = Path(file_path).expanduser()
    if not (path.is_file() or path.is_dir()):
        raise FileNotFoundError(f"not found: {path}")

    doc_id = _document_id_for(dataset_id, path)
    stored_source, stored_content = _stage_source(path, cfg, dataset_id, doc_id)

    topology_file = (profile.unified_topology or profile.indexing_topology if profile else None) or DEFAULT_UNIFIED_TOPOLOGY
    pipeline = _load_pipeline(topology_file)
    _inject_indexing_runtime(pipeline, cfg, indexing_opts)

    skip_embedding = bool(indexing_opts.get("skip_embedding") or cfg.embedding is None)
    run_inputs: dict[str, dict] = {
        "loader": {"path": str(path)},
        "splitter": {
            "dataset_id": dataset_id,
            "document_id": doc_id,
            "document_name": path.name,
            "use_hierarchical": indexing_opts.get("use_hierarchical"),
            "metadata": metadata,
        },
    }
    
    # Satisfy mandatory inputs for components NOT in the indexing path to bypass validation
    graph_inputs = pipeline.inputs()
    for name in ["query_embedder", "fts5", "graph", "vector", "joiner", "reranker", "parent"]:
        if name in graph_inputs:
            needed = graph_inputs[name]
            if name == "query_embedder":
                if "text" in needed: run_inputs.setdefault(name, {})["text"] = ""
            elif name == "fts5":
                if "query" in needed: run_inputs.setdefault(name, {})["query"] = ""
                if "dataset_ids" in needed: run_inputs.setdefault(name, {})["dataset_ids"] = []
                if "enabled" in needed: run_inputs.setdefault(name, {})["enabled"] = False
            elif name == "graph":
                if "query" in needed: run_inputs.setdefault(name, {})["query"] = ""
                if "dataset_ids" in needed: run_inputs.setdefault(name, {})["dataset_ids"] = []
                if "enabled" in needed: run_inputs.setdefault(name, {})["enabled"] = False
                if "top_k" in needed: run_inputs.setdefault(name, {})["top_k"] = 1
            elif name == "vector":
                if "embedding" in needed: run_inputs.setdefault(name, {})["embedding"] = []
                if "dataset_ids" in needed: run_inputs.setdefault(name, {})["dataset_ids"] = []
                if "top_k" in needed: run_inputs.setdefault(name, {})["top_k"] = 1
            elif name == "joiner":
                if "keyword_documents" in needed: run_inputs.setdefault(name, {})["keyword_documents"] = []
                if "semantic_documents" in needed: run_inputs.setdefault(name, {})["semantic_documents"] = []
                if "graph_documents" in needed: run_inputs.setdefault(name, {})["graph_documents"] = []
            elif name == "reranker":
                if "documents" in needed: run_inputs.setdefault(name, {})["documents"] = []
                if "query" in needed: run_inputs.setdefault(name, {})["query"] = ""
                if "enabled" in needed: run_inputs.setdefault(name, {})["enabled"] = False
            elif name == "parent":
                if "documents" in needed: run_inputs.setdefault(name, {})["documents"] = []
                if "enabled" in needed: run_inputs.setdefault(name, {})["enabled"] = False

    if skip_embedding and "embedder" in pipeline.graph.nodes and "documents" in graph_inputs.get("embedder", {}):
        run_inputs.setdefault("embedder", {})["documents"] = []

    result = pipeline.run(run_inputs, include_outputs_from={"loader", "splitter", "embedder", "writer", "qdrant_writer"})


    loader_out = result.get("loader", {})
    splitter_out = result.get("splitter", {})
    embedder_out = result.get("embedder", {}) or {}
    documents = embedder_out.get("documents") or splitter_out.get("documents") or []
    has_vector = bool(embedder_out.get("has_vector", False))

    stored_content.write_text(_resolve_text(loader_out), encoding="utf-8", errors="replace")
    combined_metadata = _combined_metadata(loader_out, metadata)
    _decorate_documents(documents, stored_source, stored_content, path, loader_out,
                        has_vector, combined_metadata)

    return {
        "dataset_id": dataset_id,
        "document_id": doc_id,
        "name": path.name,
        "chunks_count": int(splitter_out.get("chunks_count", len(documents))),
        "parent_chunks_count": int(splitter_out.get("parent_chunks_count", 0)),
        "is_hierarchical": any(d.meta.get("is_hierarchical") for d in documents),
        "has_vector": has_vector,
        "source_path": str(stored_source),
        "content_path": str(stored_content),
    }


# --- Retrieval --------------------------------------------------------------

def run_retrieval(
    cfg: Config,
    query: str,
    dataset_ids: list[str],
    retrieval_opts: dict[str, Any],
    vector_similarity_weight: float | None = None,
    fusion: str | None = None,
    parent_chunk_replace: bool | None = None,
    metadata_condition: dict | None = None,
    profile: PipelineProfile | None = None,
) -> dict:
    topology_file = (profile.unified_topology or profile.retrieval_topology if profile else None) or DEFAULT_UNIFIED_TOPOLOGY
    pipeline = _load_pipeline(topology_file)
    _inject_retrieval_runtime(pipeline, cfg)

    weight = float(
        vector_similarity_weight if vector_similarity_weight is not None
        else retrieval_opts.get("hybrid_alpha", 0.5)
    )
    if cfg.embedding is None or not cfg.embedding.is_configured:
        weight = 0.0

    effective_fusion = (fusion or retrieval_opts.get("fusion") or "rrf").lower()
    effective_parent = bool(
        parent_chunk_replace if parent_chunk_replace is not None
        else retrieval_opts.get("parent_chunk_replace", True)
    )
    top_k = int(retrieval_opts.get("top_k", 200))
    top_n = int(retrieval_opts.get("top_n", 12))
    rrf_k = int(retrieval_opts.get("rrf_k", 60))
    keyword = bool(retrieval_opts.get("keyword", True))
    use_reranker = bool(retrieval_opts.get("use_reranker", False))
    rerank_top_n = int(retrieval_opts.get("rerank_top_n", top_n))

    run_inputs: dict[str, dict] = {
        "query_embedder": {"text": query if weight > 0.0 else ""},
        "fts5": {
            "query": query,
            "dataset_ids": dataset_ids,
            "top_k": top_k,
            "enabled": keyword,
        },
        "graph": {
            "query": query,
            "dataset_ids": dataset_ids,
            "top_k": top_k,
            "enabled": True,
        },
        "vector": {"dataset_ids": dataset_ids, "top_k": top_k},
        "joiner": {
            "fusion": effective_fusion,
            "vector_weight": weight,
            "rrf_k": rrf_k,
            "metadata_condition": metadata_condition,
        },
        "reranker": {
            "query": query,
            "top_n": rerank_top_n,
            "enabled": use_reranker,
        },
        "parent": {"enabled": effective_parent},
    }

    # Satisfy mandatory inputs for components NOT in the retrieval path to bypass validation
    graph_inputs = pipeline.inputs()
    for name in ["loader", "splitter", "embedder", "writer"]:
        if name in graph_inputs:
            needed = graph_inputs[name]
            if name == "loader":
                if "path" in needed: run_inputs.setdefault(name, {})["path"] = ""
            elif name == "splitter":
                if "text" in needed: run_inputs.setdefault(name, {})["text"] = ""
                if "documents" in needed: run_inputs.setdefault(name, {})["documents"] = []
                if "dataset_id" in needed: run_inputs.setdefault(name, {})["dataset_id"] = ""
                if "document_id" in needed: run_inputs.setdefault(name, {})["document_id"] = ""
                if "document_name" in needed: run_inputs.setdefault(name, {})["document_name"] = ""
            elif name == "embedder":
                if "documents" in needed: run_inputs.setdefault(name, {})["documents"] = []
            elif name == "writer":
                if "documents" in needed: run_inputs.setdefault(name, {})["documents"] = []

    # Final inputs should only contain entries the graph actually expects
    final_inputs = {}
    for name, inputs in run_inputs.items():
        if name in graph_inputs:
            # Filter keys to only what's needed for this component
            final_inputs[name] = {k: v for k, v in inputs.items() if k in graph_inputs[name]}

    result = pipeline.run(final_inputs, include_outputs_from={"parent"})

    docs = result["parent"]["documents"]
    items = [_doc_to_item(d, effective_parent) for d in docs[:top_n]]
    return {"total": len(docs), "items": items}


def _doc_to_item(doc, parent_replace: bool) -> dict:
    meta = doc.meta or {}
    child = meta.get("child_content") or doc.content or ""
    is_hier = bool(meta.get("is_hierarchical"))
    content = (doc.content or child) if (parent_replace and is_hier) else child
    return {
        "id": doc.id,
        "chunk_id": doc.id,
        "dataset_id": meta.get("dataset_id"),
        "document_id": meta.get("document_id"),
        "document_name": meta.get("document_name"),
        "position": int(meta.get("position", 0)),
        "content": content,
        "child_content": child,
        "parent_content": meta.get("parent_content", ""),
        "parent_id": int(meta.get("parent_id", 0)),
        "child_id": int(meta.get("child_id", meta.get("position", 0))),
        "is_hierarchical": is_hier,
        "is_contextual": bool(meta.get("is_contextual")),
        "metadata": meta.get("metadata") or {},
        "similarity": float(doc.score or 0.0),
        "vector_similarity": float(meta.get("vector_similarity", 0.0)),
        "term_similarity": float(meta.get("term_similarity", 0.0)),
        "graph_similarity": float(meta.get("graph_similarity", 0.0)),
    }


def _document_id_for(dataset_id: str, path: Path) -> str:
    if path.is_dir():
        size = sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
        raw = f"{dataset_id}|{path.resolve()}|dir|{size}|{path.stat().st_mtime_ns}"
    else:
        stat = path.stat()
        raw = f"{dataset_id}|{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
    return hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()[:20]


load_builtin_registry()
