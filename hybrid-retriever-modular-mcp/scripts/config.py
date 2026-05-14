"""Shim: re-export ``retriever.config``."""
from retriever.config import *  # noqa: F401,F403
from retriever.config import (  # noqa: F401  (explicit for static analyzers)
    Config,
    EmbeddingConfig,
    IngestConfig,
    QdrantConfig,
    SearchConfig,
    load_config,
)
