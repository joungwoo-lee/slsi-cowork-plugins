"""Optional parent-chunk replacement for hierarchical chunks."""
from __future__ import annotations

from typing import List

from haystack import Document, component


@component
class ParentChunkReplacer:
    """Swap a child chunk's content for its parent content when configured.

    The original child text is preserved on ``Document.meta["child_content"]``
    so downstream formatters can still cite the precise child span.
    """

    @component.output_types(documents=List[Document])
    def run(self, documents: List[Document], enabled: bool = True) -> dict:
        if not enabled:
            for doc in documents:
                doc.meta.setdefault("child_content", doc.content)
            return {"documents": documents}
        out: list[Document] = []
        for doc in documents:
            meta = doc.meta or {}
            child = doc.content or ""
            parent = meta.get("parent_content") or child
            new_meta = dict(meta)
            new_meta["child_content"] = child
            content = parent if meta.get("is_hierarchical") else child
            out.append(Document(id=doc.id, content=content or child, meta=new_meta, score=doc.score))
        return {"documents": out}
