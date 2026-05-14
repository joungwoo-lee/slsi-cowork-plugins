"""Shim: legacy ``scripts.search.hybrid_search`` -> Haystack retrieval pipeline.

The public function signature, kwargs, and response shape are preserved; the
implementation is delegated to ``retriever.api.hybrid_search`` which runs the
modular Haystack pipeline defined in ``retriever.pipelines.retrieval``.
"""
from __future__ import annotations

from retriever.api import hybrid_search as _hybrid_search


def hybrid_search(*args, **kwargs):
    """Backward-compatible facade -- forwards to ``retriever.api.hybrid_search``."""
    return _hybrid_search(*args, **kwargs)
