"""Custom Haystack indexing pipeline for the ``email`` profile.

Topology:
EmailSourceLoader -> EmailMarkdownConverter -> HierarchicalSplitter -> HttpDocumentEmbedder -> LocalQdrantWriter
"""
from __future__ import annotations
from typing import Any
from haystack import Pipeline
from ..components import (
    EmailSourceLoader,
    EmailMarkdownConverter,
    HierarchicalSplitter,
    HttpDocumentEmbedder,
    LocalQdrantWriter,
)
from ..config import Config

def build_email_indexing_pipeline(cfg: Config, indexing_opts: dict[str, Any]) -> Pipeline:
    pipeline = Pipeline()
    
    pipeline.add_component("loader", EmailSourceLoader())
    pipeline.add_component("converter", EmailMarkdownConverter())
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
    
    pipeline.connect("loader.raw_emails", "converter.raw_emails")
    pipeline.connect("converter.documents", "splitter.documents")
    pipeline.connect("splitter.documents", "embedder.documents")
    pipeline.connect("embedder.documents", "qdrant_writer.documents")
    pipeline.connect("embedder.has_vector", "qdrant_writer.has_vector")
    
    return pipeline
