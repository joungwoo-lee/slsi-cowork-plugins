"""Shim: legacy ``scripts.ingest.upload_document`` -> Haystack indexing pipeline.

The public function signature and response shape are preserved; the work is
delegated to ``retriever.api.upload_document`` which runs the modular
Haystack pipeline defined in ``retriever.pipelines.indexing``.

Re-exports lower-level helpers (``read_text``, ``chunk_text``,
``hierarchical_records``, ``document_id_for``) because they appear in the
legacy public surface and may be imported by external tools or notebooks.
"""
from __future__ import annotations

from retriever.api import upload_document as _upload_document
from retriever.components.file_loader import _read_text as read_text  # noqa: F401
from retriever.components.hierarchical_splitter import (  # noqa: F401
    _chunk_text as chunk_text,
    _flat_records,
    _hierarchical_records as hierarchical_records,
)
from retriever.pipelines.indexing import _document_id_for as document_id_for  # noqa: F401


def upload_document(*args, **kwargs):
    """Backward-compatible facade -- forwards to ``retriever.api.upload_document``."""
    return _upload_document(*args, **kwargs)
