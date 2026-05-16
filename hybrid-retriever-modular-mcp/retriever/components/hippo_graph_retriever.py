"""HippoGraph hybrid retriever component.

Combines HippoRAG and Graph Neighborhood search into one list.
Can be named 'graph' in the topology to receive 'query' and 'dataset_ids'
from the existing engine.py without modifying module code.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

from haystack import Document, component

from .graph_retriever import GraphChunkRetriever
from .hipporag_retriever import HippoRAGRetriever


@component
class HippoGraphRetriever:
    """Expansion + PPR hybrid retriever."""

    def __init__(self, data_root: str = "") -> None:
        self.data_root = data_root
        self._graph_retriever = GraphChunkRetriever(data_root=data_root)
        self._hippo_retriever = HippoRAGRetriever(data_root=data_root)

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

        # Update data_root in case it was injected after init
        self._graph_retriever.data_root = self.data_root
        self._hippo_retriever.data_root = self.data_root

        # 1. Run Graph Neighborhood
        graph_out = self._graph_retriever.run(query, dataset_ids, top_k=top_k, enabled=True)
        graph_docs = graph_out.get("documents", [])

        # 2. Run HippoRAG
        hippo_out = self._hippo_retriever.run(query, dataset_ids, top_k=top_k, enabled=True)
        hippo_docs = hippo_out.get("documents", [])

        # 3. Merge results (Simple union with score normalization for now)
        # We'll use the graph port of HybridJoiner to pass these.
        # HybridJoiner will treat them as a single source.
        
        by_id: dict[str, Document] = {}
        
        # We'll normalize Hippo scores to [0, 1] relative to their own set
        if hippo_docs:
            h_max = max(d.score for d in hippo_docs) if hippo_docs else 1.0
            for d in hippo_docs:
                d.score = d.score / h_max if h_max > 0 else 0.0
                by_id[d.id] = d
                d.meta["hippo_score"] = d.score
                d.meta["graph_score"] = 0.0 # Placeholder for joiner

        # Add graph docs, preferring their presence but merging scores if exists
        for d in graph_docs:
            if d.id in by_id:
                # If in both, we can take the max or sum. 
                # Let's take max to represent 'strongest signal'
                existing = by_id[d.id]
                existing.score = max(existing.score, d.score)
                existing.meta["graph_score"] = d.score
            else:
                by_id[d.id] = d
                d.meta["graph_score"] = d.score
                d.meta["hippo_score"] = 0.0

        # Sort and return
        merged = sorted(by_id.values(), key=lambda d: d.score, reverse=True)
        return {"documents": merged[:top_k]}
