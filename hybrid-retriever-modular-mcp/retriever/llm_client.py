"""External chat-completions LLM client.

Mirrors :class:`EmbeddingClient`: URL + bearer key + optional x-dep-ticket /
x-system-name headers + verify_ssl toggle. Used by the HippoRAG OpenIE
extractor (offline ingest) and the query-entity extractor (online search).

The wire shape is the OpenAI ``/v1/chat/completions`` contract — both
OpenAI and any compatible self-hosted endpoint (vLLM, Together, internal
gateway) accept the same payload. JSON-mode helper requests
``response_format={"type":"json_object"}`` and tolerates servers that
ignore the flag by parsing the first JSON object in the response.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Sequence

from .config import LLMConfig

log = logging.getLogger(__name__)
_MAX_ATTEMPTS = 5
_MIN_INTERVAL_SEC = 0.2
_HARD_FAIL_STATUS = {400, 401, 403, 404}

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


class LLMClient:
    def __init__(self, cfg: LLMConfig) -> None:
        self.cfg = cfg
        if not cfg.api_url:
            raise ValueError("LLM_API_URL is empty")
        if not cfg.model:
            raise ValueError("LLM_MODEL is empty")

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

    def chat(
        self,
        messages: Sequence[dict],
        *,
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.cfg.model,
            "messages": list(messages),
            "temperature": float(self.cfg.temperature if temperature is None else temperature),
            "max_tokens": int(self.cfg.max_tokens if max_tokens is None else max_tokens),
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return self._post_with_retry(payload)

    def chat_json(
        self,
        messages: Sequence[dict],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict:
        """Same as ``chat`` but parses the response as a JSON object.

        Falls back to extracting the first ``{...}`` block when the server
        returned extra prose alongside the JSON.
        """
        raw = self.chat(messages, json_mode=True, temperature=temperature, max_tokens=max_tokens)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            m = _JSON_OBJECT_RE.search(raw)
            if not m:
                raise ValueError(f"LLM did not return JSON; got: {raw[:200]!r}")
            return json.loads(m.group(0))

    def _throttle(self) -> None:
        wait = _MIN_INTERVAL_SEC - (time.monotonic() - self._last_call_at)
        if wait > 0:
            time.sleep(wait)

    def _post_with_retry(self, payload: dict) -> str:
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
                return self._parse_text(resp.json())
            except RuntimeError:
                raise
            except Exception as exc:
                last_exc = exc
                time.sleep(float(min(2**attempt, 16)))
        raise RuntimeError(
            f"LLM API failed after {_MAX_ATTEMPTS} attempts "
            f"(url={self.cfg.api_url}, model={self.cfg.model!r}): {last_exc}"
        )

    @staticmethod
    def _parse_text(body: dict) -> str:
        choices = body.get("choices") or []
        if not choices:
            raise ValueError(f"unexpected LLM response shape: keys={list(body)[:5]}")
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if content is None:
            content = choices[0].get("text", "")
        if not isinstance(content, str):
            raise ValueError(f"unexpected LLM content type: {type(content).__name__}")
        return content


def _format_http_error(resp, cfg: LLMConfig) -> str:
    body_preview = ""
    try:
        body_preview = resp.text[:300]
    except Exception:
        pass
    return (
        f"LLM API rejected request: HTTP {resp.status_code} from {cfg.api_url} "
        f"(model={cfg.model!r}). Check LLM_API_KEY / LLM_MODEL / endpoint. "
        f"Response body (truncated): {body_preview!r}"
    )
