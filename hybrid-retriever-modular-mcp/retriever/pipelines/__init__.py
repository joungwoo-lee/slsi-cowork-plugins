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

# Alias for backward compatibility if any
profiles = type("profiles", (), {
    "get": get_profile,
    "names": list_profile_names,
    "describe": describe_profiles,
    "sync_with_disk": sync_profiles_with_disk,
    "register": register,
})

__all__ = [
    "run_indexing",
    "run_retrieval",
    "PipelineProfile",
    "profiles",
    "describe_profiles",
    "get_profile",
    "list_profile_names",
    "register",
    "sync_profiles_with_disk",
]
