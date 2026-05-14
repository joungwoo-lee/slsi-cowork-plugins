from __future__ import annotations
import hashlib
import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

from haystack import Document, Pipeline

from .. import storage, components
from ..config import Config
from ..hypster_config import select_indexing, select_retrieval
from ..stores import SqliteFts5DocumentStore

logger = logging.getLogger(__name__)

PIPELINES_DIR = Path(__file__).parent
REGISTRY_PATH = PIPELINES_DIR / "registry.json"

@dataclass(frozen=True)
class PipelineProfile:
    name: str
    description: str
    indexing_overrides: dict[str, Any] = field(default_factory=dict)
    retrieval_overrides: dict[str, Any] = field(default_factory=dict)
    search_kwargs: dict[str, Any] = field(default_factory=dict)
    indexing_topology: Optional[str] = None
    retrieval_topology: Optional[str] = None

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
    return [{"name": p.name, "description": p.description, "indexing_overrides": p.indexing_overrides, "retrieval_overrides": p.retrieval_overrides, "search_kwargs": p.search_kwargs} for p in _REGISTRY.values()]

def load_builtin_registry():
    if not REGISTRY_PATH.exists(): return
    with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    for name, item in data.items():
        register(PipelineProfile(name=name, **item))

def sync_profiles_with_disk(cfg: Config):
    json_path = cfg.data_root / "pipelines.json"
    if not json_path.exists(): return
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for name, item in data.items():
                register(PipelineProfile(name=name, **item))
    except Exception as e:
        logger.error(f"Failed to load profiles from {json_path}: {e}")

# --- Pipeline Execution Engine ---

def run_indexing(cfg: Config, dataset_id: str, file_path: str, indexing_opts: dict, metadata: dict = None, profile: PipelineProfile = None) -> dict:
    path = Path(file_path).expanduser()
    if not (path.is_file() or path.is_dir()): raise FileNotFoundError(f"not found: {path}")
    
    doc_id = _document_id_for(dataset_id, path)
    doc_dir = cfg.document_dir(dataset_id, doc_id)
    doc_dir.mkdir(parents=True, exist_ok=True)
    stored_source = cfg.source_path(dataset_id, doc_id, path.name)
    stored_content = cfg.content_path(dataset_id, doc_id)
    
    if path.is_dir():
        if stored_source.exists(): shutil.rmtree(stored_source, ignore_errors=True)
        shutil.copytree(path, stored_source)
    else: shutil.copy2(path, stored_source)

    # Build pipeline from JSON topology or default
    topology_file = (profile.indexing_topology if profile else None) or "default_indexing.json"
    topology_path = PIPELINES_DIR / topology_file
    
    with open(topology_path, "r", encoding="utf-8") as f:
        pipeline = Pipeline.loads(f.read())
    
    # Inject dynamic parameters into components before running
    # This is a bit of a hack since Haystack doesn't have a clean API for this on built pipelines
    for name, component in pipeline.graph.nodes.items():
        instance = component.get("instance")
        if hasattr(instance, "max_chars") and "max_file_chars" in indexing_opts:
            instance.max_chars = int(indexing_opts["max_file_chars"])
        if name == "splitter" and hasattr(instance, "chunk_chars"):
            instance.chunk_chars = int(indexing_opts["chunk_chars"])
            instance.chunk_overlap = int(indexing_opts["chunk_overlap"])
        if name == "embedder" and hasattr(instance, "api_url"):
            instance.api_url = cfg.embedding.api_url
            instance.api_key = cfg.embedding.api_key
            instance.dim = cfg.embedding.dim
        if name == "qdrant_writer" and hasattr(instance, "data_root"):
            instance.data_root = str(cfg.data_root)

    result = pipeline.run({
        "loader": {"path": str(path)},
        "splitter": {"dataset_id": dataset_id, "document_id": doc_id, "document_name": path.name, "use_hierarchical": indexing_opts.get("use_hierarchical"), "metadata": metadata},
        "embedder": {"documents": []} if indexing_opts.get("skip_embedding") else {},
    }, include_outputs_from={"loader", "splitter", "embedder"})

    loader_out = result["loader"]
    splitter_out = result["splitter"]
    embedder_out = result.get("embedder", {})
    documents = embedder_out.get("documents") or splitter_out.get("documents") or []
    has_vector = bool(embedder_out.get("has_vector", False))

    text = loader_out.get("text") or (f"Multi-email: {len(loader_out['raw_emails'])}" if "raw_emails" in loader_out else "")
    stored_content.write_text(text, encoding="utf-8", errors="replace")

    loader_meta = loader_out.get("email_metadata") or (loader_out["raw_emails"][0] if loader_out.get("raw_emails") and len(loader_out["raw_emails"]) == 1 else None)
    combined_metadata = {**(loader_meta or {}), **(metadata or {})}

    for doc in documents:
        doc.meta.update({"document_name": path.name, "source_path": str(stored_source), "content_path": str(stored_content), "size_bytes": int(loader_out.get("size_bytes") or path.stat().st_size if path.is_file() else 0), "has_vector": has_vector, "document_metadata": combined_metadata})
        chunk_meta = doc.meta.get("metadata") or {}
        combined = {**combined_metadata, **chunk_meta}
        doc.meta["metadata"] = combined
        for k, v in combined.items():
            if k not in doc.meta: doc.meta[k] = v

    store = SqliteFts5DocumentStore(cfg)
    store.write_documents(documents)

    return {"dataset_id": dataset_id, "document_id": doc_id, "name": path.name, "chunks_count": int(splitter_out.get("chunks_count", len(documents))), "parent_chunks_count": int(splitter_out.get("parent_chunks_count", 0)), "is_hierarchical": any(d.meta.get("is_hierarchical") for d in documents), "has_vector": has_vector, "source_path": str(stored_source), "content_path": str(stored_content)}

def run_retrieval(cfg: Config, query: str, dataset_ids: list[str], retrieval_opts: dict, vector_similarity_weight: float = None, fusion: str = None, parent_chunk_replace: bool = None, metadata_condition: dict = None, profile: PipelineProfile = None) -> dict:
    topology_file = (profile.retrieval_topology if profile else None) or "default_retrieval.json"
    topology_path = PIPELINES_DIR / topology_file
    
    with open(topology_path, "r", encoding="utf-8") as f:
        pipeline = Pipeline.loads(f.read())

    weight = float(vector_similarity_weight if vector_similarity_weight is not None else retrieval_opts["hybrid_alpha"])
    if not (cfg.embedding.api_url and cfg.embedding.dim > 0): weight = 0.0
    
    # Inject dynamic params
    for name, component in pipeline.graph.nodes.items():
        instance = component.get("instance")
        if name == "query_embedder" and hasattr(instance, "api_url"):
            instance.api_url = cfg.embedding.api_url
            instance.api_key = cfg.embedding.api_key
            instance.dim = cfg.embedding.dim
        if name == "fts5" and hasattr(instance, "data_root"): instance.data_root = str(cfg.data_root)
        if name == "vector" and hasattr(instance, "data_root"): instance.data_root = str(cfg.data_root)

    result = pipeline.run({
        "query_embedder": {"text": query if weight > 0.0 else ""},
        "fts5": {"query": query, "dataset_ids": dataset_ids, "top_k": int(retrieval_opts["top_k"]), "enabled": bool(retrieval_opts.get("keyword", True))},
        "vector": {"dataset_ids": dataset_ids, "top_k": int(retrieval_opts["top_k"])},
        "joiner": {"fusion": (fusion or retrieval_opts["fusion"] or "linear").lower(), "vector_weight": weight, "rrf_k": int(retrieval_opts["rrf_k"]), "metadata_condition": metadata_condition},
        "parent": {"enabled": bool(parent_chunk_replace if parent_chunk_replace is not None else retrieval_opts["parent_chunk_replace"])},
    }, include_outputs_from={"parent"})

    docs = result["parent"]["documents"]
    items = [_doc_to_item(d, bool(parent_chunk_replace if parent_chunk_replace is not None else retrieval_opts["parent_chunk_replace"])) for d in docs[:int(retrieval_opts["top_n"])]]
    return {"total": len(docs), "items": items}

def _doc_to_item(doc, parent_replace: bool) -> dict:
    meta = doc.meta or {}
    child = meta.get("child_content") or doc.content or ""
    is_hier = bool(meta.get("is_hierarchical"))
    return {"id": doc.id, "chunk_id": doc.id, "dataset_id": meta.get("dataset_id"), "document_id": meta.get("document_id"), "document_name": meta.get("document_name"), "position": int(meta.get("position", 0)), "content": (doc.content or child) if (parent_replace and is_hier) else child, "child_content": child, "parent_content": meta.get("parent_content", ""), "parent_id": int(meta.get("parent_id", 0)), "child_id": int(meta.get("child_id", meta.get("position", 0))), "is_hierarchical": is_hier, "is_contextual": bool(meta.get("is_contextual")), "metadata": meta.get("metadata") or {}, "similarity": float(doc.score or 0.0), "vector_similarity": float(meta.get("vector_similarity", 0.0)), "term_similarity": float(meta.get("term_similarity", 0.0))}

def _document_id_for(dataset_id: str, path: Path) -> str:
    if path.is_dir():
        size = sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
        raw = f"{dataset_id}|{path.resolve()}|dir|{size}|{path.stat().st_mtime_ns}"
    else:
        stat = path.stat()
        raw = f"{dataset_id}|{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
    return hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()[:20]

load_builtin_registry()
