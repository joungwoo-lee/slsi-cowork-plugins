"""Pipeline registry + execution engine for the modular retriever."""
from types import SimpleNamespace

from .engine import (
    PipelineProfile,
    describe_profiles,
    get_profile,
    list_profile_names,
    register,
    run_indexing,
    run_retrieval,
    sync_profiles_with_disk,
)

profiles = SimpleNamespace(
    get=get_profile,
    names=list_profile_names,
    describe=describe_profiles,
    sync_with_disk=sync_profiles_with_disk,
    register=register,
)

__all__ = [
    "PipelineProfile",
    "describe_profiles",
    "get_profile",
    "list_profile_names",
    "profiles",
    "register",
    "run_indexing",
    "run_retrieval",
    "sync_profiles_with_disk",
]
