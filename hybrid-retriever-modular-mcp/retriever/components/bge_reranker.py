"""BGE cross-encoder reranker component.

Re-scores fused candidates with a BAAI BGE reranker (default
``BAAI/bge-reranker-v2-m3``) so the top-N handed to ParentChunkReplacer is
ranked by a cross-encoder rather than by the linear/RRF fusion score alone.

Heavy deps (torch + FlagEmbedding) are imported lazily inside ``run`` so the
package still imports cleanly when the reranker is not used.
"""
from __future__ import annotations

from typing import List, Optional

from haystack import Document, component


@component
class BgeReranker:
    """Cross-encoder reranker built on a BAAI BGE reranker model.

    The component preserves the pre-rerank fusion score on
    ``Document.meta["pre_rerank_similarity"]`` and writes the cross-encoder
    score to ``Document.meta["rerank_score"]``. ``Document.score`` is replaced
    with the rerank score so downstream sort/cutoff behaves correctly.
    """

    def __init__(
        self,
        model: str = "BAAI/bge-reranker-v2-m3",
        use_fp16: bool = True,
        batch_size: int = 32,
        max_length: int = 512,
        device: Optional[str] = None,
    ) -> None:
        self.model = model
        self.use_fp16 = use_fp16
        self.batch_size = int(batch_size)
        self.max_length = int(max_length)
        self.device = device
        self._reranker = None

    def _ensure_loaded(self) -> None:
        if self._reranker is not None:
            return
        try:
            from FlagEmbedding import FlagReranker
        except ImportError as exc:
            raise RuntimeError(
                "BgeReranker requires FlagEmbedding; install with "
                "`pip install FlagEmbedding`"
            ) from exc
        kwargs: dict = {"use_fp16": bool(self.use_fp16)}
        if self.device:
            kwargs["device"] = self.device
        self._reranker = FlagReranker(self.model, **kwargs)

    @component.output_types(documents=List[Document])
    def run(
        self,
        documents: List[Document],
        query: str = "",
        top_n: int = 12,
        enabled: bool = True,
    ) -> dict:
        if not documents:
            return {"documents": []}
        cutoff = int(top_n) if top_n and int(top_n) > 0 else len(documents)
        if not enabled or not query:
            return {"documents": list(documents)[:cutoff]}

        self._ensure_loaded()
        pairs = [[query, (d.content or "")] for d in documents]
        scores = self._reranker.compute_score(
            pairs,
            batch_size=self.batch_size,
            max_length=self.max_length,
            normalize=True,
        )
        if isinstance(scores, (int, float)):
            scores = [float(scores)]
        else:
            scores = [float(s) for s in scores]

        rescored: list[Document] = []
        for doc, score in zip(documents, scores):
            meta = dict(doc.meta or {})
            meta.setdefault("pre_rerank_similarity", float(doc.score or 0.0))
            meta["rerank_score"] = score
            rescored.append(
                Document(
                    id=doc.id,
                    content=doc.content,
                    meta=meta,
                    score=score,
                )
            )
        rescored.sort(key=lambda d: d.score or 0.0, reverse=True)
        return {"documents": rescored[:cutoff]}
