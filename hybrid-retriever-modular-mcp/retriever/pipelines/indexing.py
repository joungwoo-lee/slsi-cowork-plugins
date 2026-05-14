"""Indexing pipeline: file -> chunks -> (optional embedding) -> stores.

Wires together the modular components defined under ``retriever.components``
and exposes ``run_indexing(cfg, dataset_id, file_path, ...)`` whose response
shape is byte-equivalent to the legacy ``scripts.ingest.upload_document``.

The pipeline materialises the same on-disk artifacts (copied source file +
canonical ``content.txt``) so previously ingested data remains queryable
without re-ingest.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from haystack import Pipeline

from ..components import (
    HierarchicalSplitter,
    HttpDocumentEmbedder,
    LocalFileLoader,
    LocalQdrantWriter,
)
from ..config import Config
from ..stores import SqliteFts5DocumentStore


def build_indexing_pipeline(cfg: Config, indexing_opts: dict[str, Any]) -> Pipeline:
    """Build a Haystack Pipeline for one ingest call.

    Components are wired so that downstream nodes can consume earlier outputs
    explicitly via ``pipeline.run({...})`` input dicts in ``run_indexing``.
    """
    pipeline = Pipeline()
    pipeline.add_component("loader", LocalFileLoader(max_chars=int(indexing_opts["max_file_chars"])))
    pipeline.add_component(
        "splitter",
        HierarchicalSplitter(
            chunk_chars=indexing_opts["chunk_chars"],
            chunk_overlap=indexing_opts["chunk_overlap"],
            parent_chunk_chars=indexing_opts["parent_chunk_chars"],
            parent_chunk_overlap=indexing_opts["parent_chunk_overlap"],
            child_chunk_chars=indexing_opts["child_chunk_chars"],
            child_chunk_overlap=indexing_opts["child_chunk_overlap"],
        ),
    )
    pipeline.add_component("embedder", HttpDocumentEmbedder(cfg.embedding))
    pipeline.add_component("qdrant_writer", LocalQdrantWriter(cfg))
    pipeline.connect("loader.text", "splitter.text")
    pipeline.connect("splitter.documents", "embedder.documents")
    pipeline.connect("embedder.documents", "qdrant_writer.documents")
    pipeline.connect("embedder.has_vector", "qdrant_writer.has_vector")
    return pipeline


def run_indexing(
    cfg: Config,
    dataset_id: str,
    file_path: str,
    *,
    indexing_opts: dict[str, Any],
    metadata: dict | None = None,
    builder=None,
) -> dict:
    """Execute the indexing pipeline end-to-end and persist on-disk artifacts.

    Steps:
      1. Resolve canonical document_id (sha1 of dataset|path|size|mtime),
         copy the source file under the dataset folder, and write the
         decoded content.txt -- preserving the legacy on-disk layout.
      2. Run the Haystack pipeline (loader -> splitter -> embedder -> Qdrant).
      3. Persist chunks via ``SqliteFts5DocumentStore.write_documents``,
         which also indexes FTS5 with kiwipiepy tokenisation.

    Returns the same dict shape as ``scripts.ingest.upload_document``.
    """
    path = Path(file_path).expanduser()
    if not (path.is_file() or path.is_dir()):
        raise FileNotFoundError(f"file or directory not found: {path}")
    doc_id = _document_id_for(dataset_id, path)
    doc_dir = cfg.document_dir(dataset_id, doc_id)
    doc_dir.mkdir(parents=True, exist_ok=True)
    stored_source = cfg.source_path(dataset_id, doc_id, path.name)
    stored_content = cfg.content_path(dataset_id, doc_id)
    if path.is_dir():
        # Pre-converted email-mcp folder (or any structured source) -- copy
        # the whole tree under the document's storage dir so future tools
        # (read_attachment, etc.) can still find the originals.
        if stored_source.exists():
            shutil.rmtree(stored_source, ignore_errors=True)
        shutil.copytree(path, stored_source)
    else:
        shutil.copy2(path, stored_source)

    pipeline = (builder or build_indexing_pipeline)(cfg, indexing_opts)
    result = pipeline.run(
        {
            "loader": {"path": str(path)},
            "splitter": {
                "dataset_id": dataset_id,
                "document_id": doc_id,
                "document_name": path.name,
                "use_hierarchical": indexing_opts.get("use_hierarchical"),
                "metadata": metadata,
            },
            "embedder": {"documents": []} if indexing_opts.get("skip_embedding") else {},
        },
        include_outputs_from={"loader", "splitter", "embedder", "qdrant_writer"},
    )

    loader_out = result["loader"]
    splitter_out = result["splitter"]
    embedder_out = result.get("embedder", {})
    documents = embedder_out.get("documents") or splitter_out.get("documents") or []
    has_vector = bool(embedder_out.get("has_vector", False))

    if "text" in loader_out:
        stored_content.write_text(loader_out["text"], encoding="utf-8", errors="replace")
    elif "raw_emails" in loader_out:
        # For multi-email sources (PST), we write a summary or the first email's body
        # to stored_content just to keep the file existing.
        summary = f"Multi-email source containing {len(loader_out['raw_emails'])} messages."
        stored_content.write_text(summary, encoding="utf-8")

    # Loader-provided structured metadata (e.g. EmailSourceLoader emits
    # email_metadata for single files or it's folded into Document.meta already)
    loader_meta = loader_out.get("email_metadata") if isinstance(loader_out.get("email_metadata"), dict) else None
    combined_metadata: dict[str, Any] | None
    if loader_meta and metadata:
        combined_metadata = {**loader_meta, **metadata}
    elif loader_meta:
        combined_metadata = dict(loader_meta)
    else:
        combined_metadata = metadata

    fallback_size = path.stat().st_size if path.is_file() else 0
    for doc in documents:
        # Standardize for both Haystack components and e2e_stdio.py expectations:
        # 1. document metadata fields must be top-level in doc.meta
        # 2. 'metadata' nested key must exist and contain both chunk and document fields
        
        chunk_meta = doc.meta.get("metadata") or {}
        combined = {**(combined_metadata or {}), **chunk_meta}
        
        doc.meta.update(
            {
                "document_name": path.name,
                "source_path": str(stored_source),
                "content_path": str(stored_content),
                "size_bytes": int(loader_out.get("size_bytes") or fallback_size),
                "has_vector": has_vector,
                "metadata": combined,
                "document_metadata": combined_metadata,
            }
        )
        # Flatten everything into top-level for FTS5/metadata_condition
        for k, v in combined.items():
            if k not in doc.meta:
                doc.meta[k] = v
    store = SqliteFts5DocumentStore(cfg)
    store.write_documents(documents)

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


def _document_id_for(dataset_id: str, path: Path) -> str:
    """Stable id for a file OR a directory source.

    Files use ``size`` + ``mtime_ns`` (legacy behavior). Directories use
    their own mtime plus a recursive content fingerprint so two distinct
    email-mcp mail dirs do not collide.
    """
    if path.is_dir():
        size = sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
        try:
            mtime_ns = path.stat().st_mtime_ns
        except OSError:
            mtime_ns = 0
        raw = f"{dataset_id}|{path.resolve()}|dir|{size}|{mtime_ns}"
    else:
        stat = path.stat()
        raw = f"{dataset_id}|{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
    return hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()[:20]
