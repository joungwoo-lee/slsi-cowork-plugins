from __future__ import annotations
from typing import Any, List, Optional
from haystack import Document, component

@component
class HierarchicalSplitter:
    """Stateless chunker that returns Haystack Documents ready for indexing."""

    def __init__(
        self,
        chunk_chars: int = 512,
        chunk_overlap: int = 50,
        parent_chunk_chars: int = 1024,
        parent_chunk_overlap: int = 100,
        child_chunk_chars: int = 256,
        child_chunk_overlap: int = 50,
    ) -> None:
        self._cfg = {
            "chunk_chars": int(chunk_chars),
            "chunk_overlap": int(chunk_overlap),
            "parent_chunk_chars": int(parent_chunk_chars),
            "parent_chunk_overlap": int(parent_chunk_overlap),
            "child_chunk_chars": int(child_chunk_chars),
            "child_chunk_overlap": int(child_chunk_overlap),
        }

    @component.output_types(documents=List[Document], chunks_count=int, parent_chunks_count=int)
    def run(
        self,
        text: Optional[str] = None,
        documents: Optional[List[Document]] = None,
        dataset_id: str = "",
        document_id: str = "",
        document_name: str = "",
        use_hierarchical: Any = None,
        metadata: dict | None = None,
    ) -> dict:
        all_docs: list[Document] = []
        total_chunks = 0
        total_parents = 0
        
        # If text is provided, wrap it in a Document for unified processing
        if text is not None:
            input_docs = [Document(content=text, meta={"metadata": metadata or {}})]
        elif documents is not None:
            input_docs = documents
        else:
            raise ValueError("HierarchicalSplitter requires either 'text' or 'documents'")

        for doc_idx, input_doc in enumerate(input_docs):
            # For multi-document sources, we might need unique IDs
            doc_id = input_doc.meta.get("mail_id") or document_id
            if documents and len(documents) > 1 and doc_id == document_id:
                doc_id = f"{document_id}_{doc_idx}"
            
            doc_name = input_doc.meta.get("document_name") or document_name
            doc_meta_base = input_doc.meta.get("metadata") or metadata or {}
            
            records = _make_records(input_doc.content or "", self._cfg, use_hierarchical)
            if not records: continue
            
            for pos, rec in enumerate(records):
                chunk_id = f"{doc_id}:{pos}"
                doc_meta = {
                    "dataset_id": dataset_id,
                    "document_id": doc_id,
                    "document_name": doc_name,
                    "position": pos,
                    "original_child_content": rec["original_child_content"],
                    "parent_content": rec["parent_content"],
                    "parent_id": rec["parent_id"],
                    "child_id": rec["child_id"],
                    "is_hierarchical": rec["is_hierarchical"],
                    "is_contextual": rec["is_contextual"],
                    "metadata": doc_meta_base,
                }
                all_docs.append(Document(id=chunk_id, content=rec["child_content"], meta=doc_meta))
            
            total_chunks += len(records)
            total_parents += len({r["parent_id"] for r in records if r["is_hierarchical"]})

        return {
            "documents": all_docs,
            "chunks_count": total_chunks,
            "parent_chunks_count": total_parents,
        }

def _chunk_text(text: str, chunk_chars: int, overlap: int) -> list[str]:
    text = text.strip()
    if not text: return []
    chunks: list[str] = []
    step = max(1, chunk_chars - max(0, overlap))
    for start in range(0, len(text), step):
        chunk = text[start : start + chunk_chars].strip()
        if chunk: chunks.append(chunk)
        if start + chunk_chars >= len(text): break
    return chunks

def _make_records(text: str, cfg: dict[str, int], use_hierarchical: Any) -> list[dict]:
    mode = str(use_hierarchical).lower() if use_hierarchical is not None else "false"
    if mode in ("true", "full"):
        return _hierarchical_records(text, cfg, parent_mode=("full" if mode == "full" else "normal"))
    return _flat_records(_chunk_text(text, cfg["chunk_chars"], cfg["chunk_overlap"]))

def _flat_records(chunks: list[str]) -> list[dict]:
    return [{"child_content": text, "original_child_content": text, "parent_content": text, "parent_id": 0, "child_id": idx, "global_position": idx, "is_hierarchical": False, "is_contextual": False} for idx, text in enumerate(chunks)]

def _hierarchical_records(text: str, cfg: dict[str, int], parent_mode: str = "normal") -> list[dict]:
    if parent_mode == "full":
        child_chunks = _chunk_text(text, cfg["child_chunk_chars"], cfg["child_chunk_overlap"])
        parents = [(0, text, child_chunks)]
    else:
        parent_chunks = _chunk_text(text, cfg["parent_chunk_chars"], cfg["parent_chunk_overlap"])
        parents = [(pid, p, _chunk_text(p, cfg["child_chunk_chars"], cfg["child_chunk_overlap"])) for pid, p in enumerate(parent_chunks)]
    records: list[dict] = []
    for parent_id, parent, child_chunks in parents:
        for child_id, child in enumerate(child_chunks):
            records.append({"child_content": child, "original_child_content": child, "parent_content": parent, "parent_id": parent_id, "child_id": child_id, "global_position": len(records), "is_hierarchical": True, "is_contextual": False})
    return records
