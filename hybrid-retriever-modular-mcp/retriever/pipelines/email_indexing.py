"""Custom Haystack indexing pipeline for the ``email`` profile.

Topology mirrors the default indexing pipeline (loader → splitter → embedder
→ qdrant_writer) but swaps the loader for ``EmailFileLoader`` so .eml files
and email-mcp pre-converted folders both work through the same MCP tool.

The loader's ``email_metadata`` output is read off the pipeline result in
``run_indexing`` and merged into each emitted ``Document.meta["metadata"]``
-- so subject / sender / received become first-class filterable fields on
the retrieval side via the standard ``metadata_condition`` argument.
"""
from __future__ import annotations

from typing import Any

from haystack import Pipeline

from ..components import (
    EmailFileLoader,
    HierarchicalSplitter,
    HttpDocumentEmbedder,
    LocalQdrantWriter,
)
from ..config import Config


def build_email_indexing_pipeline(cfg: Config, indexing_opts: dict[str, Any]) -> Pipeline:
    """Wire the email-aware indexing pipeline.

    Topology is identical to the default builder; only the loader differs.
    Keeping the rest of the pipeline shared means hierarchical chunking,
    embedding, and Qdrant write all behave the same so retrieval doesn't
    need an email-specific code path.
    """
    pipeline = Pipeline()
    pipeline.add_component("loader", EmailFileLoader(max_chars=int(indexing_opts["max_file_chars"])))
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
