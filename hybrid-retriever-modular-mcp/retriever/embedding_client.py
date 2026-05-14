"""External embedding API client.

Defaults to ``verify_ssl=True`` (set by :class:`EmbeddingConfig`). Set
``EMBEDDING_VERIFY_SSL=false`` only when targeting an internal endpoint with
a self-signed certificate — never against a public provider.
"""
from __future__ import annotations

import logging
import time
from typing import Sequence

from .config import EmbeddingConfig

log = logging.getLogger(__name__)
_MAX_ATTEMPTS = 5
_MIN_INTERVAL_SEC = 0.5
_HARD_FAIL_STATUS = {400, 401, 403, 404}  # do not retry — caller config is wrong


class EmbeddingClient:
    def __init__(self, cfg: EmbeddingConfig) -> None:
        self.cfg = cfg
        if not cfg.api_url:
            raise ValueError("EMBEDDING_API_URL is empty")
        if cfg.dim <= 0:
            raise ValueError(f"EMBEDDING_DIM must be > 0, got {cfg.dim!r}")

        import requests

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
            except Exception:
                pass
        self._last_call_at = 0.0

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), self.cfg.batch_size):
            out.extend(self._embed_once(list(texts[start : start + self.cfg.batch_size])))
        return out

    def _throttle(self) -> None:
        wait = _MIN_INTERVAL_SEC - (time.monotonic() - self._last_call_at)
        if wait > 0:
            time.sleep(wait)

    def _embed_once(self, chunk: list[str]) -> list[list[float]]:
        payload = {"model": self.cfg.model, "input": chunk}
        last_exc: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            self._throttle()
            self._last_call_at = time.monotonic()
            try:
                resp = self.session.post(self.cfg.api_url, json=payload, timeout=self.cfg.timeout_sec)
                if resp.status_code == 429:
                    time.sleep(5.0 * (attempt + 1))
                    last_exc = RuntimeError(f"HTTP 429 from {self.cfg.api_url}")
                    continue
                if resp.status_code in _HARD_FAIL_STATUS:
                    raise RuntimeError(_format_http_error(resp, self.cfg))
                resp.raise_for_status()
                vectors = self._parse_vectors(resp.json())
                if any(len(v) != self.cfg.dim for v in vectors):
                    raise ValueError(
                        f"embedding dim mismatch: expected {self.cfg.dim}, "
                        f"got {[len(v) for v in vectors]} (model='{self.cfg.model}')"
                    )
                return vectors
            except RuntimeError as exc:
                # Hard-fail responses already carry a precise message — surface them
                # immediately instead of burning four more retries.
                raise
            except Exception as exc:
                last_exc = exc
                time.sleep(float(min(2**attempt, 16)))
        raise RuntimeError(
            f"embedding API failed after {_MAX_ATTEMPTS} attempts "
            f"(url={self.cfg.api_url}, model={self.cfg.model!r}): {last_exc}"
        )

    @staticmethod
    def _parse_vectors(body: dict) -> list[list[float]]:
        items = body.get("data") or body.get("embeddings") or []
        if not items:
            raise ValueError(f"unexpected response shape: keys={list(body)[:5]}")
        if isinstance(items[0], dict):
            return [item["embedding"] for item in sorted(items, key=lambda d: d.get("index", 0))]
        return [list(v) for v in items]


def _format_http_error(resp, cfg: EmbeddingConfig) -> str:
    """Build a precise, secrets-free error message for hard failures."""
    body_preview = ""
    try:
        body_preview = resp.text[:300]
    except Exception:
        pass
    return (
        f"embedding API rejected request: HTTP {resp.status_code} from {cfg.api_url} "
        f"(model={cfg.model!r}, dim={cfg.dim}). "
        f"Check EMBEDDING_API_KEY / EMBEDDING_MODEL / EMBEDDING_DIM. "
        f"Response body (truncated): {body_preview!r}"
    )
