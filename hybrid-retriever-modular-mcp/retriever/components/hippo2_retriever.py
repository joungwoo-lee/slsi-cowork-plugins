"""Hippo2 retriever component.

Wraps ``hippo2_query.search`` so it slots into a Haystack Pipeline.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

from haystack import Document, component

from .. import storage
from ..config import Config
from ..hippo2 import query as hippo2_query
from ..hippo2 import ppr as hippo2_ppr


@component
class Hippo2Retriever:
    """Retrieval using Hippo2 PPR scoring."""

    def __init__(self, data_root: str = "") -> None:
        self.data_root = data_root
        self._ppr_engine = None

    def _get_ppr_engine(self, cfg: Config) -> hippo2_ppr.PPREngine:
        if self._ppr_engine is None:
            self._ppr_engine = hippo2_ppr.PPREngine(cfg, cfg.hippo2)
        return self._ppr_engine

    @component.output_types(documents=List[Document])
    def run(
        self,
        query: str,
        dataset_ids: List[str],
        top_k: int = 200,
        enabled: bool = True,
    ) -> dict:
        if not enabled or not query or not dataset_ids or not self.data_root:
            return {"documents": []}

        cfg = Config(data_root=Path(self.data_root))
        if not cfg.llm or not cfg.llm.is_configured:
            return {"documents": []}

        try:
            with storage.sqlite_session(cfg) as conn:
                engine = self._get_ppr_engine(cfg)
                result = hippo2_query.search(
                    cfg,
                    conn,
                    engine,
                    query.strip(),
                    dataset_ids,
                    top_chunks=top_k,
                )
        except Exception:
            # If Hippo2 fails (e.g. no entities found), return empty
            return {"documents": []}

        docs: list[Document] = []
        for rank, chunk in enumerate(result.chunks, 1):
            meta = {
                "dataset_id": chunk["dataset_id"],
                "document_id": chunk["document_id"],
                "document_name": chunk["document_name"],
                "position": int(chunk["position"]),
                "hippo_rank": rank,
                "hippo_score": float(chunk["score"]),
                "matched_entities": chunk.get("matched_entities", []),
            }
            docs.append(
                Document(
                    id=chunk["chunk_id"],
                    content=chunk["content"],
                    meta=meta,
                    score=float(chunk["score"]),
                )
            )
        return {"documents": docs}
