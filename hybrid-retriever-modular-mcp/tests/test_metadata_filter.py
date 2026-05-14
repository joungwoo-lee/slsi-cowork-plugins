"""Tests for storage.metadata_matches — type-aware metadata predicate."""
from __future__ import annotations

import unittest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retriever.storage import metadata_matches, _filter_metadata


class MetadataMatchesTest(unittest.TestCase):
    def test_empty_condition_matches_everything(self) -> None:
        self.assertTrue(metadata_matches({}, None))
        self.assertTrue(metadata_matches({"a": 1}, {}))

    def test_scalar_equality_preserves_type(self) -> None:
        # The legacy str(actual) != str(v) version would have matched here
        # because str(2024) == "2024". The new implementation must reject.
        self.assertFalse(metadata_matches({"year": 2024}, {"year": "2024"}))
        self.assertTrue(metadata_matches({"year": 2024}, {"year": 2024}))
        self.assertFalse(metadata_matches({"draft": True}, {"draft": "true"}))
        self.assertTrue(metadata_matches({"draft": True}, {"draft": True}))

    def test_list_containment(self) -> None:
        self.assertTrue(metadata_matches({"tag": "alpha"}, {"tag": ["alpha", "beta"]}))
        self.assertFalse(metadata_matches({"tag": "gamma"}, {"tag": ["alpha", "beta"]}))

    def test_dollar_in_operator(self) -> None:
        self.assertTrue(metadata_matches({"tag": "alpha"}, {"tag": {"$in": ["alpha", "beta"]}}))
        self.assertFalse(metadata_matches({"tag": "gamma"}, {"tag": {"$in": ["alpha", "beta"]}}))

    def test_missing_key_fails(self) -> None:
        self.assertFalse(metadata_matches({}, {"a": 1}))

    def test_filter_metadata_checks_top_level_then_nested(self) -> None:
        rows = [
            {"document_id": "doc-1", "metadata": {"year": 2024}, "content": "a"},
            {"document_id": "doc-2", "metadata": {"year": 2025}, "content": "b"},
        ]
        # Top-level filter
        self.assertEqual(
            [r["document_id"] for r in _filter_metadata(rows, {"document_id": "doc-1"})],
            ["doc-1"],
        )
        # Nested metadata filter with int comparison
        self.assertEqual(
            [r["document_id"] for r in _filter_metadata(rows, {"year": 2025})],
            ["doc-2"],
        )
        # Nested would-fail string comparison (regression for the old str() bug)
        self.assertEqual(_filter_metadata(rows, {"year": "2025"}), [])


if __name__ == "__main__":
    unittest.main()
