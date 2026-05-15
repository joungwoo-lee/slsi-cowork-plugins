"""SQLite FTS5 writer component."""
from __future__ import annotations

from pathlib import Path
from typing import List

from haystack import Document, component

from ..config import Config
from ..stores import SqliteFts5DocumentStore


@component
class SqliteFts5Writer:
    """Write chunk documents into the local SQLite FTS5 index."""

    def __init__(self, data_root: str = "") -> None:
        self.data_root = data_root

    @component.output_types(written=int)
    def run(self, documents: List[Document]) -> dict:
        if not documents or not self.data_root:
            return {"written": 0}

        cfg = Config(data_root=Path(self.data_root))
        store = SqliteFts5DocumentStore(cfg)
        return {"written": int(store.write_documents(documents))}
