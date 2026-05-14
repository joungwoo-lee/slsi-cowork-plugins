"""Korean morpheme tokenization helpers backed by kiwipiepy.

The FTS5 unicode61 tokenizer only splits on whitespace/punctuation, so Korean
eojeol tokens like "보고서를" never match a stem query like "보고서". We solve
this by pre-tokenizing both indexed text and query text with kiwipiepy: each
eojeol is broken into morpheme `form` strings (joined by spaces) before being
handed to FTS5. The downstream FTS5 schema therefore stays simple
(`tokenize='unicode61'`) while still supporting Korean stem matching including
2-character queries like "메일" or "엔진".
"""
from __future__ import annotations

import re
import threading

_kiwi = None
_kiwi_lock = threading.Lock()

_FTS5_QUERY_STRIP = re.compile(r'["\(\)\*:\-\^]+')


def _get_kiwi():
    global _kiwi
    if _kiwi is None:
        with _kiwi_lock:
            if _kiwi is None:
                from kiwipiepy import Kiwi
                _kiwi = Kiwi()
    return _kiwi


def tokenize_for_index(text: str) -> str:
    """Tokenize text for storage in an FTS5 column.

    Returns morpheme forms joined by single spaces. Empty input -> "".
    """
    if not text:
        return ""
    tokens = _get_kiwi().tokenize(text)
    return " ".join(t.form for t in tokens if t.form)


def tokenize_for_query(query: str) -> str:
    """Tokenize a search query into an FTS5 MATCH expression.

    Each morpheme is wrapped in double-quotes so it becomes an FTS5 phrase,
    and phrases are space-separated (implicit AND).
    """
    if not query:
        return ""
    cleaned = _FTS5_QUERY_STRIP.sub(" ", query)
    forms = [t.form for t in _get_kiwi().tokenize(cleaned) if t.form.strip()]
    if not forms:
        return ""
    return " ".join(f'"{f}"' for f in forms)
