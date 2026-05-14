"""Pre-wired Haystack pipelines for indexing and retrieval.

Profiles (named bundles of components + config) live in ``profiles`` so
third parties can register new compositions without touching the builders.
"""
from . import profiles
from .indexing import build_indexing_pipeline, run_indexing
from .profiles import PipelineProfile
from .retrieval import build_retrieval_pipeline, run_retrieval

__all__ = [
    "build_indexing_pipeline",
    "run_indexing",
    "build_retrieval_pipeline",
    "run_retrieval",
    "PipelineProfile",
    "profiles",
]
