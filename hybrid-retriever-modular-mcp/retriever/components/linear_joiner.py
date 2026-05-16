"""Linear fusion component: min-max keyword + weighted semantic + graph bonus."""
from __future__ import annotations

from typing import List

from haystack import Document, component

from ._joiner_common import docs_to_rows, merged_documents, normalize_generic, normalize_keyword, normalize_semantic


@component
class LinearJoiner:
    @component.output_types(documents=List[Document])
    def run(
        self,
        keyword_documents: List[Document],
        semantic_documents: List[Document] | None = None,
        graph_documents: List[Document] | None = None,
        vector_weight: float = 0.5,
        metadata_condition: dict | None = None,
    ) -> dict:
        semantic_documents = semantic_documents or []
        graph_documents = graph_documents or []
        kw_scores = normalize_keyword(docs_to_rows(keyword_documents, score_key="fts_score"))
        sem_scores = normalize_semantic(docs_to_rows(semantic_documents, score_key="vector_score"))
        graph_scores = normalize_generic(docs_to_rows(graph_documents, score_key="graph_score"))

        weight = max(0.0, min(1.0, float(vector_weight)))
        merged: list[Document] = []
        for doc in merged_documents(keyword_documents, semantic_documents, graph_documents, metadata_condition):
            kw = kw_scores.get(doc.id, 0.0)
            sem = sem_scores.get(doc.id, 0.0)
            graph_score = graph_scores.get(doc.id, 0.0)
            score = (1.0 - weight) * kw + weight * sem + 0.2 * graph_score
            merged.append(Document(
                id=doc.id,
                content=doc.content,
                meta={
                    **doc.meta,
                    "term_similarity": round(kw, 6),
                    "vector_similarity": round(sem, 6),
                    "graph_similarity": round(graph_score, 6),
                },
                score=round(score, 6),
            ))
        merged.sort(key=lambda d: d.score or 0.0, reverse=True)
        return {"documents": merged}
