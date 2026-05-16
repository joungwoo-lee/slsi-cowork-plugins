"""Morpheme tokenization for FTS5 — Korean + English.

Indexing: kiwipiepy splits Korean eojeols into morpheme forms so that
"보고서를" → "보고서 를", enabling stem queries like "보고서" to match.
English tokens pass through as-is (unicode61 handles word splitting).

Querying: only *content* morphemes go into the MATCH expression.
Grammatical tokens (particles 조사, endings 어미, affixes 접사, punctuation)
are dropped because they don't appear in document content and would turn
AND-logic into a 0-result trap. All surviving terms are OR-joined so that
BM25 ranking handles relevance — no arbitrary AND across query words.

English stop words are removed the same way.
"""
from __future__ import annotations

import re
import threading

_kiwi = None
_kiwi_lock = threading.Lock()

_FTS5_QUERY_STRIP = re.compile(r'["\(\)\*:\-\^]+')

# kiwipiepy POS tag prefixes that are purely grammatical — drop from queries.
# J* = 조사(particles), E* = 어미(endings), X* = 접사(affixes), S* = 구두점/기호
# VCP/VCN = copula(이다/아니다), IC = 감탄사, MM/MJ = 관형사/접속부사
_DROP_TAG_PREFIXES = ("J", "E", "X", "S", "VCP", "VCN", "IC")

_EN_STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "to", "of", "in", "on",
    "at", "by", "for", "with", "about", "as", "into", "from", "and",
    "but", "or", "not", "so", "than", "too", "very", "it", "its",
    "i", "me", "my", "we", "our", "you", "your", "he", "she", "they",
    "him", "her", "his", "them", "their", "there", "here",
    "this", "that", "these", "those", "what", "which", "who", "how",
    "when", "where", "use", "used", "using",
})


def _get_kiwi():
    global _kiwi
    if _kiwi is None:
        with _kiwi_lock:
            if _kiwi is None:
                from kiwipiepy import Kiwi
                _kiwi = Kiwi()
    return _kiwi


def tokenize_for_index(text: str) -> str:
    """Original text (for Porter) + Morphemes (for Korean)."""
    if not text:
        return ""
    morphemes = " ".join(t.form for t in _get_kiwi().tokenize(text) if t.form)
    return f"{text} {morphemes}"


def tokenize_for_query(query: str) -> str:
    """Content morphemes only, AND-joined for FTS5 MATCH.

    Drops: Korean particles/endings/affixes/punctuation, English stop words,
    any token with no alphanumeric character.
    Joins survivors with spaces (implicit AND).
    """
    if not query:
        return ""
    cleaned = _FTS5_QUERY_STRIP.sub(" ", query)
    tokens = _get_kiwi().tokenize(cleaned)

    kept: list[str] = []
    for tok in tokens:
        form = tok.form.strip()
        if not form or not any(c.isalnum() for c in form):
            continue
        tag = str(getattr(tok, "tag", "") or "")
        if any(tag.startswith(p) for p in _DROP_TAG_PREFIXES):
            continue
        if tag.startswith("SL") or (form.isascii() and form.isalpha()):
            # Latin/English token
            if form.lower() in _EN_STOPWORDS or len(form) < 2:
                continue
        kept.append(form)

    if not kept:
        raw = [w for w in cleaned.split() if len(w) >= 2]
        return " ".join(f'"{w}"' for w in raw[:10]) if raw else ""

    return " ".join(f'"{f}"' for f in kept)
