"""Reciprocal-rank fusion component for keyword, semantic, and graph candidates."""
from __future__ import annotations

from typing import List

from haystack import Document, component

from ._joiner_common import docs_to_rows, merged_documents, normalize_generic, normalize_keyword, normalize_semantic, rrf_scores


@component
class RrfJoiner:
    @component.output_types(documents=List[Document])
    def run(
        self,
        keyword_documents: List[Document],
        semantic_documents: List[Document] | None = None,
        graph_documents: List[Document] | None = None,
        rrf_k: int = 60,
        metadata_condition: dict | None = None,
    ) -> dict:
        semantic_documents = semantic_documents or []
        graph_documents = graph_documents or []
        kw_rows = docs_to_rows(keyword_documents, score_key="fts_score")
        sem_rows = docs_to_rows(semantic_documents, score_key="vector_score")
        graph_rows = docs_to_rows(graph_documents, score_key="graph_score")
        kw_scores = normalize_keyword(kw_rows)
        sem_scores = normalize_semantic(sem_rows)
        graph_scores = normalize_generic(graph_rows)
        fused = rrf_scores(kw_rows, sem_rows, graph_rows, rrf_k)

        merged: list[Document] = []
        for doc in merged_documents(keyword_documents, semantic_documents, graph_documents, metadata_condition):
            kw = kw_scores.get(doc.id, 0.0)
            sem = sem_scores.get(doc.id, 0.0)
            graph_score = graph_scores.get(doc.id, 0.0)
            merged.append(Document(
                id=doc.id,
                content=doc.content,
                meta={
                    **doc.meta,
                    "term_similarity": round(kw, 6),
                    "vector_similarity": round(sem, 6),
                    "graph_similarity": round(graph_score, 6),
                },
                score=round(fused.get(doc.id, 0.0), 6),
            ))
        merged.sort(key=lambda d: d.score or 0.0, reverse=True)
        return {"documents": merged}
