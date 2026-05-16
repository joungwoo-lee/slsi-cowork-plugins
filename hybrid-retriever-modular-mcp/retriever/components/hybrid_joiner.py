"""Compatibility shim for older imports.

Prefer ``retriever.components.linear_joiner.LinearJoiner`` or
``retriever.components.rrf_joiner.RrfJoiner``.
"""
from .linear_joiner import LinearJoiner
from .rrf_joiner import RrfJoiner

HybridJoiner = RrfJoiner

__all__ = ["HybridJoiner", "LinearJoiner", "RrfJoiner"]
