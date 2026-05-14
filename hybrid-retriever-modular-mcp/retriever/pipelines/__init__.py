"""Pre-wired Haystack pipelines for indexing and retrieval."""
from .indexing import build_indexing_pipeline, run_indexing
from .retrieval import build_retrieval_pipeline, run_retrieval

__all__ = [
    "build_indexing_pipeline",
    "run_indexing",
    "build_retrieval_pipeline",
    "run_retrieval",
]
