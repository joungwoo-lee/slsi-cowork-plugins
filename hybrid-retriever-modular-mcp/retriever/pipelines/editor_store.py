"""Shared persistence for visual pipeline editing.

Used by both the local browser editor and the MCP ``save_pipeline`` tool so
topology/profile writes follow one code path.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..config import Config, DEFAULT_ENV_PATH, load_config
from .node_topology import from_haystack_dict, is_node_centric, to_haystack_dict

PIPELINES_DIR = Path(__file__).resolve().parent
REGISTRY_PATH = PIPELINES_DIR / "registry.json"


def user_profiles_path(cfg: Config | None = None) -> Path:
    if cfg is not None:
        return cfg.data_root / "pipelines.json"
    
    # Load config to get the correct data_root (respecting .env)
    try:
        cfg = load_config()
        return cfg.data_root / "pipelines.json"
    except Exception:
        # Fallback to simple env check if config load fails
        data_root = Path(os.environ.get("RETRIEVER_DATA_ROOT") or r"C:\Retriever_Data")
        return data_root / "pipelines.json"


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def normalise_topology(raw: dict[str, Any]) -> dict[str, Any]:
    """Coerce a UI/MCP topology blob into the haystack standard dict.

    Accepts either node-centric (``{nodes: [...]}``) or standard
    (``{components, connections}``). Always returns the standard shape so the
    haystack ``Pipeline`` loader can consume it.
    """
    if is_node_centric(raw):
        return to_haystack_dict(raw)
    components = {}
    for cname, cdef in (raw.get("components") or {}).items():
        if not isinstance(cdef, dict):
            continue
        components[cname] = {
            "type": cdef.get("type") or cdef.get("cls"),
            "init_parameters": cdef.get("init_parameters") or cdef.get("params") or {},
        }
    connections = []
    for edge in raw.get("connections") or []:
        if not isinstance(edge, dict):
            continue
        sender = edge.get("sender")
        receiver = edge.get("receiver")
        if sender and receiver:
            connections.append({"sender": sender, "receiver": receiver})
    return {
        "metadata": raw.get("metadata") or {},
        "max_runs_per_component": raw.get("max_runs_per_component", 100),
        "components": components,
        "connections": connections,
        "connection_type_validation": bool(raw.get("connection_type_validation", True)),
    }


# Per-node fields the editor/storage path is allowed to round-trip even though
# the Haystack standard format (components + connections) doesn't carry them.
# Listed explicitly so a typo in a third-party topology doesn't silently
# propagate through saves.
_PRESERVED_NODE_FIELDS: tuple[str, ...] = ("answer_template",)


def topology_for_storage(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert any incoming topology blob into the node-centric on-disk form.

    The Haystack intermediate shape (``components`` + ``connections``) drops
    per-node extras like ``answer_template``. Capture those before normalising
    and re-attach them by node name afterwards so they survive editor saves.
    """
    extras: dict[str, dict[str, Any]] = {}
    if is_node_centric(raw):
        for node in raw.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            node_name = node.get("name")
            if not isinstance(node_name, str):
                continue
            preserved = {k: node[k] for k in _PRESERVED_NODE_FIELDS if k in node}
            if preserved:
                extras[node_name] = preserved

    standard = normalise_topology(raw)
    node_centric = from_haystack_dict(standard)

    if extras:
        for node in node_centric.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            extra = extras.get(node.get("name") or "")
            if extra:
                node.update(extra)
    return node_centric


def topology_for_ui(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert any topology blob into the node-centric form the editor renders."""
    if is_node_centric(raw):
        return raw
    return from_haystack_dict(normalise_topology(raw))


def _with_topology_description(blob: dict[str, Any], description: str) -> dict[str, Any]:
    """Return ``blob`` with ``metadata.description`` set (when description is non-empty)."""
    if not description:
        return blob
    out = dict(blob)
    metadata = dict(out.get("metadata") or {})
    metadata["description"] = description
    out["metadata"] = metadata
    return out


def save_pipeline_payload(
    payload: dict[str, Any],
    *,
    cfg: Config | None = None,
    pipelines_dir: Path | None = None,
    profiles_path: Path | None = None,
) -> dict[str, Any]:
    name = (payload.get("name") or "").strip()
    if not name or not name.replace("_", "").replace("-", "").isalnum():
        return {"error": "name must be alphanumeric (underscore/hyphen allowed)"}

    description = str(payload.get("description") or "")
    profile: dict[str, Any] = {
        "indexing_overrides": payload.get("indexing_overrides") or {},
        "retrieval_overrides": payload.get("retrieval_overrides") or {},
        "search_kwargs": payload.get("search_kwargs") or {},
    }

    target_pipelines_dir = pipelines_dir or PIPELINES_DIR

    def _has_topology(blob: Any) -> bool:
        return isinstance(blob, dict) and (blob.get("components") or blob.get("nodes"))

    def _store(blob: dict[str, Any]) -> dict[str, Any]:
        return _with_topology_description(topology_for_storage(blob), description)

    unified_topology = payload.get("unified_topology")
    if _has_topology(unified_topology):
        topology_file = f"{name}_unified.json"
        atomic_write_json(target_pipelines_dir / topology_file, _store(unified_topology))
        profile["unified_topology"] = topology_file
        # Also keep indexing/retrieval pointing to the same file for compatibility
        profile["indexing_topology"] = topology_file
        profile["retrieval_topology"] = topology_file

    indexing_topology = payload.get("indexing_topology")
    if _has_topology(indexing_topology):
        topology_file = f"{name}_indexing.json"
        atomic_write_json(target_pipelines_dir / topology_file, _store(indexing_topology))
        profile["indexing_topology"] = topology_file

    retrieval_topology = payload.get("retrieval_topology")
    if _has_topology(retrieval_topology):
        topology_file = f"{name}_retrieval.json"
        atomic_write_json(target_pipelines_dir / topology_file, _store(retrieval_topology))
        profile["retrieval_topology"] = topology_file

    # If no topology was supplied, keep the description on the profile so it
    # is still discoverable by ``list_pipelines`` / the search-tool schema.
    if (
        description
        and not profile.get("unified_topology")
        and not profile.get("indexing_topology")
        and not profile.get("retrieval_topology")
    ):
        profile["description"] = description

    profiles_path = profiles_path or user_profiles_path(cfg)
    profiles = read_json(profiles_path)
    profiles[name] = profile
    atomic_write_json(profiles_path, profiles)
    return {
        "status": "ok",
        "profile_path": str(profiles_path),
        "indexing_topology": profile.get("indexing_topology"),
        "retrieval_topology": profile.get("retrieval_topology"),
    }
