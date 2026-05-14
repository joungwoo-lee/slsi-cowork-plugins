"""Tests for retriever.graph.run_query — read-only enforcement + LIMIT regex.

We exercise the helper without a live Kùzu connection by stubbing only the
``execute`` and result iteration that ``run_query`` touches.
"""
from __future__ import annotations

import re
import unittest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retriever import graph as graph_mod


class _StubResult:
    def __init__(self) -> None:
        self._yielded = False

    def get_column_names(self) -> list[str]:
        return ["x"]

    def has_next(self) -> bool:
        if self._yielded:
            return False
        self._yielded = True
        return True

    def get_next(self) -> tuple:
        return (1,)


class _StubConn:
    def __init__(self) -> None:
        self.last_cypher: str | None = None

    def execute(self, cypher: str, _params: dict):
        self.last_cypher = cypher
        return _StubResult()


class GraphLimitTest(unittest.TestCase):
    def test_destructive_keyword_rejected(self) -> None:
        with self.assertRaises(ValueError):
            graph_mod.run_query(_StubConn(), "CREATE (n:Chunk)")
        with self.assertRaises(ValueError):
            graph_mod.run_query(_StubConn(), "  delete (n) ")

    def test_limit_appended_when_missing(self) -> None:
        conn = _StubConn()
        graph_mod.run_query(conn, "MATCH (n) RETURN n", limit=7)
        self.assertIn("LIMIT 7", conn.last_cypher or "")

    def test_existing_limit_is_preserved(self) -> None:
        conn = _StubConn()
        graph_mod.run_query(conn, "MATCH (n) RETURN n LIMIT 3", limit=50)
        # Must keep the user's LIMIT 3 and NOT append a second LIMIT 50.
        self.assertEqual(len(re.findall(r"\bLIMIT\s+\d+\b", conn.last_cypher or "", re.IGNORECASE)), 1)
        self.assertIn("LIMIT 3", conn.last_cypher or "")

    def test_trailing_semicolon_does_not_disable_limit(self) -> None:
        conn = _StubConn()
        graph_mod.run_query(conn, "MATCH (n) RETURN n;", limit=9)
        self.assertIn("LIMIT 9", conn.last_cypher or "")

    def test_empty_query_rejected(self) -> None:
        with self.assertRaises(ValueError):
            graph_mod.run_query(_StubConn(), "   ")


if __name__ == "__main__":
    unittest.main()
