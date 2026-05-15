"""Graph-aware chunk retriever backed by the embedded Kuzu graph."""
from __future__ import annotations

from pathlib import Path
from typing import List

from haystack import Document, component

from .. import graph, storage
from ..config import Config


@component
class GraphChunkRetriever:
    """Expand query-matched chunks through graph neighbors."""

    def __init__(self, data_root: str = "") -> None:
        self.data_root = data_root

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
        with storage.sqlite_session(cfg) as conn:
            seed_rows = storage.fts_search(conn, query, dataset_ids, max(1, min(top_k, 20)))
            if not seed_rows:
                return {"documents": []}

            gconn = graph.open_graph(cfg)
            graph.sync_graph(gconn, conn)
            scored: dict[str, float] = {}
            for seed_rank, row in enumerate(seed_rows, 1):
                seed_id = row["chunk_id"]
                scored[seed_id] = max(scored.get(seed_id, 0.0), 1.0 / seed_rank)
                for neighbor_id, neighbor_score in _neighbor_scores(gconn, seed_id):
                    score = neighbor_score / seed_rank
                    if score > scored.get(neighbor_id, 0.0):
                        scored[neighbor_id] = score

            ranked_ids = [cid for cid, _ in sorted(scored.items(), key=lambda item: item[1], reverse=True)[:top_k]]
            chunks = storage.fetch_chunks(conn, ranked_ids)

        docs: list[Document] = []
        for rank, chunk_id in enumerate(ranked_ids, 1):
            chunk = chunks.get(chunk_id)
            if not chunk:
                continue
            score = float(scored.get(chunk_id, 0.0))
            meta = {
                "dataset_id": chunk["dataset_id"],
                "document_id": chunk["document_id"],
                "document_name": chunk["document_name"],
                "position": int(chunk["position"]),
                "parent_content": chunk.get("parent_content", chunk["content"]),
                "parent_id": int(chunk.get("parent_id", 0)),
                "child_id": int(chunk.get("child_id", chunk["position"])),
                "is_hierarchical": bool(chunk.get("is_hierarchical")),
                "is_contextual": bool(chunk.get("is_contextual")),
                "metadata": chunk.get("metadata", {}) or {},
                "original_child_content": chunk.get("original_content", "") or chunk["content"],
                "graph_rank": rank,
                "graph_score": score,
            }
            docs.append(Document(id=chunk_id, content=chunk["content"], meta=meta, score=score))
        return {"documents": docs}


def _neighbor_scores(conn, chunk_id: str) -> list[tuple[str, float]]:
    rows: list[tuple[str, float]] = []

    forward = conn.execute(
        """
        MATCH (c:Chunk)-[:NEXT]->(n:Chunk)
        WHERE c.id = $cid
        RETURN n.id AS chunk_id
        LIMIT 2
        """,
        {"cid": chunk_id},
    )
    while forward.has_next():
        values = forward.get_next()
        rows.append((values[0], 0.75))

    backward = conn.execute(
        """
        MATCH (p:Chunk)-[:NEXT]->(c:Chunk)
        WHERE c.id = $cid
        RETURN p.id AS chunk_id
        LIMIT 2
        """,
        {"cid": chunk_id},
    )
    while backward.has_next():
        values = backward.get_next()
        rows.append((values[0], 0.7))

    return rows
