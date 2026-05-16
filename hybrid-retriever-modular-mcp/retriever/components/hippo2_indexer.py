"""Hippo2 indexing component for modular pipeline topologies."""
from __future__ import annotations

from pathlib import Path
from typing import List

from haystack import Document, component

from .. import graph, storage
from ..config import load_config
from ..hippo2 import index as hippo2_index


@component
class Hippo2Indexer:
    """Run Hippo2 OpenIE/entity/fact indexing after chunk writers complete."""

    def __init__(
        self,
        data_root: str = "",
        rebuild_synonyms: bool = False,
        max_workers: int = 4,
    ) -> None:
        self.data_root = data_root
        self.rebuild_synonyms = rebuild_synonyms
        self.max_workers = max_workers

    @component.output_types(indexed=int, triples_written=int, entities_embedded=int, facts_embedded=int)
    def run(
        self,
        documents: List[Document],
        written: int = 0,
        vector_written: int = 0,
        enabled: bool = True,
    ) -> dict:
        if not enabled or not documents:
            return {"indexed": 0, "triples_written": 0, "entities_embedded": 0, "facts_embedded": 0}
        if int(written or 0) <= 0:
            return {"indexed": 0, "triples_written": 0, "entities_embedded": 0, "facts_embedded": 0}

        cfg = load_config()
        if self.data_root:
            cfg.data_root = Path(self.data_root)
        document_ids = sorted({
            str((doc.meta or {}).get("document_id") or "")
            for doc in documents
            if str((doc.meta or {}).get("document_id") or "").strip()
        })
        totals = {"indexed": 0, "triples_written": 0, "entities_embedded": 0, "facts_embedded": 0}
        with storage.sqlite_session(cfg) as conn:
            for document_id in document_ids:
                result = hippo2_index.index_document(
                    cfg,
                    conn,
                    document_id,
                    rebuild_synonyms_after=bool(self.rebuild_synonyms),
                    max_workers=max(1, int(self.max_workers)),
                )
                totals["indexed"] += int(result.get("chunks_processed", 0))
                totals["triples_written"] += int(result.get("triples_written", 0))
                totals["entities_embedded"] += int(result.get("entities_embedded", 0))
                totals["facts_embedded"] += int(result.get("facts_embedded", 0))
            if totals["indexed"] > 0:
                graph.mark_dirty(conn)
        return totals
