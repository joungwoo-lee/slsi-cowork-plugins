"""Thin client for the external embedding API (OpenAI-compatible by default)."""
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
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {cfg.api_key}",
                "Content-Type": "application/json",
            }
        )

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
                    self.cfg.endpoint,
                    json=payload,
                    timeout=self.cfg.timeout_sec,
                )
                resp.raise_for_status()
                body = resp.json()
                # OpenAI-compatible shape: {"data": [{"embedding": [...], "index": N}, ...]}
                items = sorted(body["data"], key=lambda d: d.get("index", 0))
                vectors = [item["embedding"] for item in items]
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
