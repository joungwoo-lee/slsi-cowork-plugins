"""Haystack pipeline components for the local retriever.

The components mirror gilad-rubin/modular-rag's decomposition but run against
this project's SQLite FTS5 + optional local Qdrant + embedded Kuzu graph.
"""
from .email_loader import EmailSourceLoader
from .email_markdown_converter import EmailMarkdownConverter
from .file_loader import LocalFileLoader
from .hierarchical_splitter import HierarchicalSplitter
from .document_embedder import HttpDocumentEmbedder, HttpTextEmbedder
from .fts5_retriever import Fts5Retriever
from .fts5_writer import SqliteFts5Writer
from .vector_retriever import LocalQdrantRetriever, LocalQdrantWriter
from .hybrid_joiner import HybridJoiner
from .parent_replace import ParentChunkReplacer
from .bge_reranker import BgeReranker

__all__ = [
    "EmailSourceLoader",
    "EmailMarkdownConverter",
    "LocalFileLoader",
    "HierarchicalSplitter",
    "HttpDocumentEmbedder",
    "HttpTextEmbedder",
    "Fts5Retriever",
    "SqliteFts5Writer",
    "LocalQdrantRetriever",
    "LocalQdrantWriter",
    "HybridJoiner",
    "ParentChunkReplacer",
    "BgeReranker",
]
