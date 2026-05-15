"""Chunk → factual triples via LLM (OpenIE).

The extractor is a thin policy layer over :class:`LLMClient`:

- prompt template asks for strict JSON with a fixed shape
- responses are validated and bounded (max triples per chunk)
- each call is keyed by sha256(chunk_content + model + prompt_version) so
  re-indexing the same corpus with the same model is free
- concurrent requests use a small threadpool (the client itself handles
  per-call retry/throttle/backoff)

Surface forms are returned verbatim — canonicalisation happens later in
``entities.py`` so the same surface "Samsung" / "samsung" / "삼성전자"
can be merged or kept separate based on canonicalisation policy.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Iterable

from ..config import HippoRAGConfig, LLMConfig
from ..llm_client import LLMClient

log = logging.getLogger(__name__)

PROMPT_VERSION = "v1"

_SYSTEM_PROMPT = (
    "You are a precise information-extraction engine. Given a passage, "
    "extract factual triples (subject, predicate, object) representing concrete "
    "relationships between named entities or noun phrases. Output strict JSON. "
    "Do not invent facts that are not in the passage."
)

_USER_TEMPLATE = (
    "Passage:\n\"\"\"\n{text}\n\"\"\"\n\n"
    "Output JSON with this exact shape:\n"
    "{{\n"
    "  \"triples\": [\n"
    "    {{\"subject\": \"...\", \"predicate\": \"...\", \"object\": \"...\"}}\n"
    "  ]\n"
    "}}\n\n"
    "Rules:\n"
    "- Subjects and objects are short noun phrases or proper nouns, max 80 chars each.\n"
    "- Predicates are concise verb-phrases in lowercase, max 40 chars (e.g. \"located in\", \"co-founded\", \"보고 대상\").\n"
    "- Skip pronouns, anaphora, and vague references. Skip if the passage is empty or pure boilerplate.\n"
    "- Maximum {max_triples} triples. Quality over quantity.\n"
    "- Respond with the JSON object only. No prose, no markdown fence."
)


@dataclass(frozen=True)
class Triple:
    subject: str
    predicate: str
    object: str

    def is_valid(self) -> bool:
        return bool(self.subject and self.predicate and self.object)


def _chunk_hash(content: str, model: str) -> str:
    h = hashlib.sha256()
    h.update(PROMPT_VERSION.encode("utf-8"))
    h.update(b"|")
    h.update(model.encode("utf-8"))
    h.update(b"|")
    h.update((content or "").encode("utf-8"))
    return h.hexdigest()


def _load_cached(conn: sqlite3.Connection, chunk_hash: str) -> list[Triple] | None:
    row = conn.execute(
        "SELECT triples_json FROM extraction_cache WHERE chunk_hash = ?",
        (chunk_hash,),
    ).fetchone()
    if not row:
        return None
    try:
        data = json.loads(row[0]) or []
    except json.JSONDecodeError:
        return None
    return [Triple(**t) for t in data if isinstance(t, dict)]


def _save_cache(conn: sqlite3.Connection, chunk_hash: str, model: str, triples: list[Triple]) -> None:
    payload = json.dumps(
        [{"subject": t.subject, "predicate": t.predicate, "object": t.object} for t in triples],
        ensure_ascii=False,
    )
    conn.execute(
        "INSERT INTO extraction_cache(chunk_hash, model, triples_json) VALUES(?, ?, ?) "
        "ON CONFLICT(chunk_hash) DO UPDATE SET triples_json = excluded.triples_json, "
        "model = excluded.model, created_at = datetime('now')",
        (chunk_hash, model, payload),
    )


def _parse_response(body: dict, max_triples: int) -> list[Triple]:
    raw = body.get("triples") if isinstance(body, dict) else None
    if not isinstance(raw, list):
        return []
    out: list[Triple] = []
    for item in raw[: max_triples * 2]:  # tolerate over-generation, trim below
        if not isinstance(item, dict):
            continue
        s = (item.get("subject") or "").strip()[:80]
        p = (item.get("predicate") or "").strip().lower()[:40]
        o = (item.get("object") or "").strip()[:80]
        t = Triple(subject=s, predicate=p, object=o)
        if t.is_valid():
            out.append(t)
        if len(out) >= max_triples:
            break
    return out


class OpenIEExtractor:
    """Stateless-ish extractor. The LLM client is reused across calls."""

    def __init__(self, llm_cfg: LLMConfig, hipporag_cfg: HippoRAGConfig) -> None:
        self.llm = LLMClient(llm_cfg)
        self.model = llm_cfg.model
        self.max_triples = max(1, int(hipporag_cfg.extraction_max_triples))
        self._cache_lock = threading.Lock()

    def extract_chunk(
        self,
        sqlite_conn: sqlite3.Connection,
        chunk_id: str,
        content: str,
    ) -> list[Triple]:
        text = (content or "").strip()
        if not text:
            return []
        digest = _chunk_hash(text, self.model)

        with self._cache_lock:
            cached = _load_cached(sqlite_conn, digest)
        if cached is not None:
            return cached

        body = self.llm.chat_json(
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _USER_TEMPLATE.format(text=text, max_triples=self.max_triples),
                },
            ]
        )
        triples = _parse_response(body, self.max_triples)

        with self._cache_lock:
            _save_cache(sqlite_conn, digest, self.model, triples)
            sqlite_conn.commit()

        return triples

    def extract_chunks(
        self,
        sqlite_conn: sqlite3.Connection,
        chunks: Iterable[tuple[str, str]],
        max_workers: int = 4,
    ) -> dict[str, list[Triple]]:
        """Run extraction over many chunks with bounded concurrency.

        ``chunks`` yields ``(chunk_id, content)`` pairs. Returns a dict
        keyed by chunk_id. The single ``sqlite_conn`` is shared; each
        cache hit/miss path takes ``_cache_lock`` so writes don't race.
        """
        items = list(chunks)
        if not items:
            return {}

        out: dict[str, list[Triple]] = {}
        with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
            futures = {
                pool.submit(self.extract_chunk, sqlite_conn, cid, content): cid
                for cid, content in items
            }
            for fut in as_completed(futures):
                cid = futures[fut]
                try:
                    out[cid] = fut.result()
                except Exception as exc:  # noqa: BLE001 — log + continue, partial result is useful
                    log.warning("OpenIE failed for chunk %s: %s", cid, exc)
                    out[cid] = []
        return out
