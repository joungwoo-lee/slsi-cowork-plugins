"""HTTP embedding components wrapping the existing EmbeddingClient.

Two thin wrappers preserve the exact retry/throttle/auth behavior of the legacy
``EmbeddingClient`` while making it usable as Haystack pipeline blocks:

- ``HttpDocumentEmbedder.run(documents)`` -> attaches ``Document.embedding``
  to each input. No-op (and ``has_vector=False``) when ``api_url`` or
  ``dim`` are not configured -- the indexing pipeline degrades gracefully to
  keyword-only mode.

- ``HttpTextEmbedder.run(text)`` -> returns ``embedding`` for query side.
"""
from __future__ import annotations

import dataclasses
from typing import List

from haystack import Document, component

from ..config import EmbeddingConfig
from ..embedding_client import EmbeddingClient


@component
class HttpDocumentEmbedder:
    """Embed a list of Documents in batches via the configured HTTP API."""

    def __init__(self, cfg: EmbeddingConfig) -> None:
        self._cfg = cfg
        self._client: EmbeddingClient | None = None

    def _ensure_client(self) -> EmbeddingClient | None:
        if not self._cfg.api_url or self._cfg.dim <= 0:
            return None
        if self._client is None:
            self._client = EmbeddingClient(self._cfg)
        return self._client

    @component.output_types(documents=List[Document], has_vector=bool)
    def run(self, documents: List[Document]) -> dict:
        client = self._ensure_client()
        if client is None or not documents:
            return {"documents": documents, "has_vector": False}
        vectors = client.embed([doc.content or "" for doc in documents])
        # Replace each Document immutably -- mutating ``embedding`` in place
        # works but Haystack flags it because the same instance may live in
        # multiple pipeline frames at once.
        embedded = [
            dataclasses.replace(doc, embedding=list(vec))
            for doc, vec in zip(documents, vectors)
        ]
        return {"documents": embedded, "has_vector": True}


@component
class HttpTextEmbedder:
    """Embed a single query string. Returns embedding=[] when disabled."""

    def __init__(self, cfg: EmbeddingConfig) -> None:
        self._cfg = cfg
        self._client: EmbeddingClient | None = None

    def _ensure_client(self) -> EmbeddingClient | None:
        if not self._cfg.api_url or self._cfg.dim <= 0:
            return None
        if self._client is None:
            self._client = EmbeddingClient(self._cfg)
        return self._client

    @component.output_types(embedding=List[float])
    def run(self, text: str) -> dict:
        client = self._ensure_client()
        if client is None or not text:
            return {"embedding": []}
        [vec] = client.embed([text])
        return {"embedding": vec}
