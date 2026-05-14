"""Tests for retriever.morph — kiwipiepy tokenization for FTS5."""
from __future__ import annotations

import unittest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retriever.morph import tokenize_for_index, tokenize_for_query


class MorphTest(unittest.TestCase):
    def test_empty_input_returns_empty_string(self) -> None:
        self.assertEqual(tokenize_for_index(""), "")
        self.assertEqual(tokenize_for_query(""), "")

    def test_korean_eojeol_is_split_into_morphemes(self) -> None:
        # "메일을" should tokenize into morphemes including "메일".
        indexed = tokenize_for_index("메일을 보낸 사람")
        self.assertIn("메일", indexed.split())

    def test_query_wraps_each_morpheme_in_quotes(self) -> None:
        expr = tokenize_for_query("프로젝트")
        # Each morpheme phrase-quoted; multiple phrases joined by spaces.
        self.assertTrue(all(part.startswith('"') and part.endswith('"') for part in expr.split()))

    def test_fts5_metacharacters_stripped_from_query(self) -> None:
        # The dangerous FTS5 metacharacters ()*:-^ must not survive into MATCH.
        # Double-quotes are *added back* deliberately around each morpheme to
        # turn them into phrase tokens — that is the safe form.
        expr = tokenize_for_query('hello("world*")')
        for ch in '(*:^':
            self.assertNotIn(ch, expr)
        # Each token is wrapped in matching quotes.
        self.assertEqual(expr.count('"') % 2, 0)


if __name__ == "__main__":
    unittest.main()
