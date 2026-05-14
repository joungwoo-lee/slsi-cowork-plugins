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

    def __init__(
        self,
        api_url: str = "",
        api_key: str = "",
        model: str = "",
        dim: int = 0,
        x_dep_ticket: str = "",
        x_system_name: str = "hybrid-retriever-modular-mcp",
        batch_size: int = 16,
        timeout_sec: int = 60,
        verify_ssl: bool = False,
    ) -> None:
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.dim = dim
        self.x_dep_ticket = x_dep_ticket
        self.x_system_name = x_system_name
        self.batch_size = batch_size
        self.timeout_sec = timeout_sec
        self.verify_ssl = verify_ssl
        self._client: EmbeddingClient | None = None

    def _ensure_client(self) -> EmbeddingClient | None:
        if not self.api_url or self.dim <= 0:
            return None
        if self._client is None:
            cfg = EmbeddingConfig(
                api_url=self.api_url,
                api_key=self.api_key,
                model=self.model,
                dim=self.dim,
                x_dep_ticket=self.x_dep_ticket,
                x_system_name=self.x_system_name,
                batch_size=self.batch_size,
                timeout_sec=self.timeout_sec,
                verify_ssl=self.verify_ssl,
            )
            self._client = EmbeddingClient(cfg)
        return self._client

    @component.output_types(documents=List[Document], has_vector=bool)
    def run(self, documents: List[Document]) -> dict:
        client = self._ensure_client()
        if client is None or not documents:
            return {"documents": documents, "has_vector": False}
        vectors = client.embed([doc.content or "" for doc in documents])
        embedded = [
            dataclasses.replace(doc, embedding=list(vec))
            for doc, vec in zip(documents, vectors)
        ]
        return {"documents": embedded, "has_vector": True}


@component
class HttpTextEmbedder:
    """Embed a single query string. Returns embedding=[] when disabled."""

    def __init__(
        self,
        api_url: str = "",
        api_key: str = "",
        model: str = "",
        dim: int = 0,
        x_dep_ticket: str = "",
        x_system_name: str = "hybrid-retriever-modular-mcp",
        batch_size: int = 16,
        timeout_sec: int = 60,
        verify_ssl: bool = False,
    ) -> None:
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.dim = dim
        self.x_dep_ticket = x_dep_ticket
        self.x_system_name = x_system_name
        self.batch_size = batch_size
        self.timeout_sec = timeout_sec
        self.verify_ssl = verify_ssl
        self._client: EmbeddingClient | None = None

    def _ensure_client(self) -> EmbeddingClient | None:
        if not self.api_url or self.dim <= 0:
            return None
        if self._client is None:
            cfg = EmbeddingConfig(
                api_url=self.api_url,
                api_key=self.api_key,
                model=self.model,
                dim=self.dim,
                x_dep_ticket=self.x_dep_ticket,
                x_system_name=self.x_system_name,
                batch_size=self.batch_size,
                timeout_sec=self.timeout_sec,
                verify_ssl=self.verify_ssl,
            )
            self._client = EmbeddingClient(cfg)
        return self._client

    @component.output_types(embedding=List[float])
    def run(self, text: str) -> dict:
        client = self._ensure_client()
        if client is None or not text:
            return {"embedding": []}
        [vec] = client.embed([text])
        return {"embedding": vec}
