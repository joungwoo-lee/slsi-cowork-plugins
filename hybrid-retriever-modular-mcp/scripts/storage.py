"""Shim: re-export ``retriever.storage``."""
from retriever.storage import *  # noqa: F401,F403
from retriever.storage import (  # noqa: F401
    INDEX_SCHEMA_VERSION,
    SCHEMA,
    ensure_collection,
    ensure_dataset,
    fetch_chunks,
    fts_search,
    open_qdrant,
    open_sqlite,
    qdrant_id,
    slug,
    sqlite_session,
    upsert_document,
    upsert_vectors,
    vector_search,
)
