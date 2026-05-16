"""Hippo2 continual-learning benchmark helpers.

The benchmark is intentionally search-engine agnostic: callers provide a
``search_fn`` so the same cases can run against a live MCP server, in-process
``hippo2.query.search``, or a deterministic test double.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Literal, Protocol


MemoryCategory = Literal["factual", "sense_making", "associative"]


@dataclass(frozen=True)
class BenchmarkCase:
    id: str
    category: MemoryCategory
    query: str
    dataset_ids: list[str]
    expected_chunk_ids: list[str] | None = None
    expected_terms: list[str] | None = None


@dataclass(frozen=True)
class CaseResult:
    id: str
    category: MemoryCategory
    passed: bool
    matched_by: str
    retrieved_chunk_ids: list[str]


@dataclass(frozen=True)
class BenchmarkReport:
    total: int
    passed: int
    by_category: dict[MemoryCategory, dict[str, float | int]]
    cases: list[CaseResult]


class SearchFn(Protocol):
    def __call__(self, query: str, dataset_ids: list[str], top_n: int) -> Iterable[dict]:
        ...


def evaluate_cases(
    cases: Iterable[BenchmarkCase],
    search_fn: SearchFn,
    *,
    top_n: int = 12,
) -> BenchmarkReport:
    results: list[CaseResult] = []
    for case in cases:
        chunks = list(search_fn(case.query, case.dataset_ids, top_n))
        chunk_ids = [str(c.get("chunk_id") or "") for c in chunks]
        texts = "\n".join(str(c.get("content") or "") for c in chunks).lower()

        expected_ids = set(case.expected_chunk_ids or [])
        if expected_ids and expected_ids.intersection(chunk_ids):
            results.append(CaseResult(case.id, case.category, True, "chunk_id", chunk_ids))
            continue

        terms = [t.lower() for t in (case.expected_terms or []) if t]
        if terms and all(term in texts for term in terms):
            results.append(CaseResult(case.id, case.category, True, "term", chunk_ids))
            continue

        results.append(CaseResult(case.id, case.category, False, "none", chunk_ids))

    by_category: dict[MemoryCategory, dict[str, float | int]] = {}
    for category in ("factual", "sense_making", "associative"):
        cat_results = [r for r in results if r.category == category]
        passed = sum(1 for r in cat_results if r.passed)
        total = len(cat_results)
        by_category[category] = {
            "total": total,
            "passed": passed,
            "accuracy": (passed / total) if total else 0.0,
        }

    passed_total = sum(1 for r in results if r.passed)
    return BenchmarkReport(
        total=len(results),
        passed=passed_total,
        by_category=by_category,
        cases=results,
    )


def cases_from_json(payload: list[dict]) -> list[BenchmarkCase]:
    """Load cases from a JSON-compatible list.

    Required fields: ``id``, ``category``, ``query``. ``dataset_ids`` defaults
    to an empty list so the caller's default dataset routing can still be used.
    """
    cases: list[BenchmarkCase] = []
    for raw in payload:
        category = raw.get("category")
        if category not in {"factual", "sense_making", "associative"}:
            raise ValueError(f"invalid Hippo2 benchmark category: {category!r}")
        cases.append(BenchmarkCase(
            id=str(raw["id"]),
            category=category,
            query=str(raw["query"]),
            dataset_ids=[str(x) for x in raw.get("dataset_ids", [])],
            expected_chunk_ids=[str(x) for x in raw.get("expected_chunk_ids", [])] or None,
            expected_terms=[str(x) for x in raw.get("expected_terms", [])] or None,
        ))
    return cases
