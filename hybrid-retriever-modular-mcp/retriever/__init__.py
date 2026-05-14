"""Modular Haystack + Hypster retriever package.

Layout mirrors gilad-rubin/modular-rag but stays self-contained for MCP:

    retriever.config              process config dataclasses
    retriever.morph               kiwipiepy tokenization
    retriever.embedding_client    sync HTTP embedding client
    retriever.graph               embedded Kuzu graph layer
    retriever.storage             low-level SQLite + Qdrant primitives
    retriever.stores.*            Haystack DocumentStore implementations
    retriever.components.*        Haystack @component pipeline blocks
    retriever.pipelines.*         pre-wired indexing / retrieval pipelines
    retriever.hypster_config      Hypster configuration spaces
    retriever.api                 high-level facade callable from MCP handlers

The MCP `scripts/*` modules remain as thin re-export shims so external
callers and existing handlers see the same surface they did before.
"""
