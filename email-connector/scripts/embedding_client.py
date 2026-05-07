"""External embedding API client.

Header / payload / response-parsing layout matches the retriever_engine project's
api/modules/retrieval/engine.py:embed_texts so that the same API gateway works
for both projects:

    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer <EMBEDDING_API_KEY>",     # if api_key set
        "x-dep-ticket":  "<EMBEDDING_API_X_DEP_TICKET>",   # if set
        "x-system-name": "<EMBEDDING_API_X_SYSTEM_NAME>",  # if set
    }
    POST <EMBEDDING_API_URL>
    body = {"model": "<EMBEDDING_MODEL>", "input": [<text>, ...]}

Response is OpenAI-compatible: either {"data": [{"embedding": [...], "index": N}, ...]}
or {"embeddings": [[...], [...]]}; both shapes are handled.
"""
from __future__ import annotations

import logging
import time
from typing import Sequence

import requests

from .config import EmbeddingConfig

log = logging.getLogger(__name__)


class EmbeddingClient:
    def __init__(self, cfg: EmbeddingConfig) -> None:
        self.cfg = cfg
        if not cfg.api_url:
            raise ValueError("EMBEDDING_API_URL is empty in .env")
        if cfg.dim <= 0:
            raise ValueError("EMBEDDING_DIM must be a positive integer")

        self.session = requests.Session()
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if cfg.api_key:
            headers["Authorization"] = f"Bearer {cfg.api_key}"
        if cfg.x_dep_ticket:
            headers["x-dep-ticket"] = cfg.x_dep_ticket
        if cfg.x_system_name:
            headers["x-system-name"] = cfg.x_system_name
        self.session.headers.update(headers)

        self.session.verify = bool(cfg.verify_ssl)
        if not self.session.verify:
            try:
                from urllib3.exceptions import InsecureRequestWarning
                import urllib3

                urllib3.disable_warnings(InsecureRequestWarning)
            except Exception:  # noqa: BLE001
                pass
            log.warning("SSL verification disabled for embedding endpoint (EMBEDDING_VERIFY_SSL=false)")

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns list aligned with input order."""
        if not texts:
            return []
        out: list[list[float]] = []
        for start in range(0, len(texts), self.cfg.batch_size):
            chunk = list(texts[start : start + self.cfg.batch_size])
            out.extend(self._embed_once(chunk))
        return out

    def _embed_once(self, chunk: list[str]) -> list[list[float]]:
        payload = {"model": self.cfg.model, "input": chunk}
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = self.session.post(
                    self.cfg.api_url,
                    json=payload,
                    timeout=self.cfg.timeout_sec,
                )
                resp.raise_for_status()
                vectors = self._parse_vectors(resp.json())
                if any(len(v) != self.cfg.dim for v in vectors):
                    raise ValueError(
                        f"embedding dim mismatch: expected {self.cfg.dim}, "
                        f"got {[len(v) for v in vectors]}"
                    )
                return vectors
            except Exception as exc:
                last_exc = exc
                wait = 2**attempt
                log.warning("embedding attempt %d failed: %s (retrying in %ds)", attempt + 1, exc, wait)
                time.sleep(wait)
        raise RuntimeError(f"embedding API failed after retries: {last_exc}")

    @staticmethod
    def _parse_vectors(body: dict) -> list[list[float]]:
        items = body.get("data")
        if items is None:
            items = body.get("embeddings", [])
        if not items:
            raise ValueError(f"unexpected response shape: keys={list(body)[:5]}")
        # OpenAI shape: list of {"embedding": [...], "index": N}
        if isinstance(items[0], dict):
            ordered = sorted(items, key=lambda d: d.get("index", 0))
            return [item["embedding"] for item in ordered]
        # Plain shape: list of vectors
        return [list(v) for v in items]
