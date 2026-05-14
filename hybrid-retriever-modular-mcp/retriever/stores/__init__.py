"""Haystack DocumentStore implementations for the local retriever."""
from .sqlite_fts5_store import SqliteFts5DocumentStore

__all__ = ["SqliteFts5DocumentStore"]
