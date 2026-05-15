"""HippoRAG knowledge-graph layer.

Sub-modules:
- ``openie``   — chunk → factual triples via LLM, cached by chunk hash
- ``entities`` — canonicalize, hash, embed, persist
- ``synonyms`` — entity-entity similarity edges
- ``ppr``      — Personalized PageRank engine with disk CSR cache
- ``index``    — orchestrator: full or incremental index for a dataset
- ``query``    — query-side: extract → link → PPR → score chunks
"""
from __future__ import annotations
