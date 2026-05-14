"""Named pipeline profiles for the modular retriever.

A profile bundles one specific combination of components and configuration
into a single name. Callers (MCP tools, notebooks) pick a profile by name and
the rest of the system resolves the right builders + Hypster overrides.

This is the extension point for new pipelines: drop a new ``PipelineProfile``
into ``register(...)`` and it becomes available everywhere -- the MCP
``search`` / ``upload_document`` tools, ``list_pipelines``, and any direct
caller of ``retriever.api``.

Built-in profiles
-----------------

- **default** -- mirrors the legacy retriever behavior: SQLite FTS5 keyword
  retrieval, optional Qdrant vector retrieval, linear hybrid fusion,
  parent-chunk replacement, kiwipiepy tokenisation. This is what every
  existing MCP call has always done, so existing consumers see no change.

- **keyword_only** -- demonstration of an alternative composition. Skips the
  vector branch entirely (forced ``vector_weight=0``) and uses RRF fusion.
  Faster, embedding-API independent, and useful for benchmarking pure-keyword
  recall against the default hybrid pipeline.

Custom profiles
---------------

Any third party can register their own profile, for example::

    from retriever.pipelines import profiles
    from retriever.pipelines.profiles import PipelineProfile

    profiles.register(PipelineProfile(
        name="rrf_strong_vector",
        description="RRF fusion biased toward vector hits",
        retrieval_overrides={"fusion": "rrf", "hybrid_alpha": 0.8},
    ))

Profiles can also supply ``build_indexing`` / ``build_retrieval`` callables
to swap the actual Haystack pipeline topology (e.g. inserting a reranker
component); when omitted, the default builders are used with the per-profile
override dicts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from haystack import Pipeline

from ..config import Config


@dataclass(frozen=True)
class PipelineProfile:
    """One bundled (indexing + retrieval) pipeline preset.

    ``indexing_overrides`` and ``retrieval_overrides`` are merged on top of the
    process ``Config`` defaults before being handed to Hypster. They can set
    any key declared in ``retriever.hypster_config``.

    ``build_indexing`` / ``build_retrieval`` are optional escape hatches for
    profiles whose topology differs from the default builders -- a custom
    builder takes ``(cfg, opts)`` (indexing) or ``(cfg,)`` (retrieval) and
    returns a wired ``haystack.Pipeline``. The default builders cover all the
    flat / hierarchical / hybrid / RRF combinations exposed today.

    ``search_kwargs`` lets a profile force per-call retrieval args that aren't
    part of the Hypster space -- e.g. clamping ``vector_similarity_weight=0``
    for a keyword-only profile so the caller can't accidentally re-enable
    vectors.
    """

    name: str
    description: str
    indexing_overrides: dict[str, Any] = field(default_factory=dict)
    retrieval_overrides: dict[str, Any] = field(default_factory=dict)
    search_kwargs: dict[str, Any] = field(default_factory=dict)
    build_indexing: Optional[Callable[[Config, dict[str, Any]], Pipeline]] = None
    build_retrieval: Optional[Callable[[Config], Pipeline]] = None


_REGISTRY: dict[str, PipelineProfile] = {}


def register(profile: PipelineProfile) -> None:
    """Register (or replace) a profile by name."""
    _REGISTRY[profile.name] = profile


def get(name: str) -> PipelineProfile:
    """Return a profile by name; falls back to ``default`` for unknown names."""
    if name in _REGISTRY:
        return _REGISTRY[name]
    if "default" in _REGISTRY:
        return _REGISTRY["default"]
    raise KeyError(f"no pipeline profile named '{name}' and no default registered")


def names() -> list[str]:
    """All registered profile names, in registration order."""
    return list(_REGISTRY.keys())


def describe() -> list[dict[str, Any]]:
    """Serializable list of profiles for inspection (used by list_pipelines)."""
    out: list[dict[str, Any]] = []
    for p in _REGISTRY.values():
        out.append(
            {
                "name": p.name,
                "description": p.description,
                "indexing_overrides": dict(p.indexing_overrides),
                "retrieval_overrides": dict(p.retrieval_overrides),
                "search_kwargs": dict(p.search_kwargs),
                "custom_indexing_builder": p.build_indexing is not None,
                "custom_retrieval_builder": p.build_retrieval is not None,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Built-in profiles
# ---------------------------------------------------------------------------

register(
    PipelineProfile(
        name="default",
        description=(
            "Legacy hybrid retriever: SQLite FTS5 + optional local Qdrant, "
            "linear fusion, parent-chunk replacement, kiwipiepy tokenisation. "
            "Every call that does not pass a 'pipeline' argument uses this."
        ),
        # Empty overrides -> all process Config defaults apply unchanged.
    )
)


register(
    PipelineProfile(
        name="keyword_only",
        description=(
            "Pure SQLite FTS5 keyword retrieval with RRF fusion. Skips the "
            "embedding API entirely; useful when the embedding endpoint is "
            "down or for benchmarking keyword recall against the default "
            "hybrid pipeline."
        ),
        indexing_overrides={"skip_embedding": True},
        # search_kwargs FORCE these at call time; retrieval_overrides would
        # only seed Hypster defaults that the caller can still override.
        # The whole point of this profile is to never touch the vector branch
        # and always use RRF, regardless of what the caller passes.
        search_kwargs={"vector_similarity_weight": 0.0, "fusion": "rrf"},
    )
)


# Email profile is registered with a deferred import to keep
# retriever/pipelines/profiles.py importable in environments that don't
# have the email components installed yet (e.g. boot-doctor sentinel runs).
def _register_email_profile() -> None:
    from .email_indexing import build_email_indexing_pipeline

    register(
        PipelineProfile(
            name="email",
            description=(
                "Email ingestion pipeline. Extracts messages from a .pst file (via Python 3.9 "
                "worker) and converts body + attachments to Markdown. Headers (subject, sender, "
                "recipients, received, folder_path) are folded into Document metadata so search "
                "can filter via metadata_condition. Retrieval uses the default hybrid pipeline."
            ),
            indexing_overrides={
                # Emails are short relative to chunk_chars defaults; keep flat
                # chunking by default so each chunk is one ~512-char span and
                # the unified header block usually lives in the first chunk.
                "use_hierarchical": "false",
            },
            build_indexing=build_email_indexing_pipeline,
        )
    )


_register_email_profile()


def sync_with_disk(cfg: Config) -> None:
    """Load additional profiles from DATA_ROOT/pipelines.json."""
    from .manager import load_and_register_profiles
    json_path = cfg.data_root / "pipelines.json"
    load_and_register_profiles(json_path)

