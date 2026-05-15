"""Shared persistence for visual pipeline editing.

Used by both the local browser editor and the MCP ``save_pipeline`` tool so
topology/profile writes follow one code path.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..config import Config

PIPELINES_DIR = Path(__file__).resolve().parent
REGISTRY_PATH = PIPELINES_DIR / "registry.json"


def user_profiles_path(cfg: Config | None = None) -> Path:
    if cfg is not None:
        return cfg.data_root / "pipelines.json"
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

    profile: dict[str, Any] = {
        "description": payload.get("description", ""),
        "indexing_overrides": payload.get("indexing_overrides") or {},
        "retrieval_overrides": payload.get("retrieval_overrides") or {},
        "search_kwargs": payload.get("search_kwargs") or {},
    }

    target_pipelines_dir = pipelines_dir or PIPELINES_DIR
    indexing_topology = payload.get("indexing_topology")
    if isinstance(indexing_topology, dict) and indexing_topology.get("components"):
        topology_file = f"{name}_indexing.json"
        atomic_write_json(target_pipelines_dir / topology_file, normalise_topology(indexing_topology))
        profile["indexing_topology"] = topology_file

    retrieval_topology = payload.get("retrieval_topology")
    if isinstance(retrieval_topology, dict) and retrieval_topology.get("components"):
        topology_file = f"{name}_retrieval.json"
        atomic_write_json(target_pipelines_dir / topology_file, normalise_topology(retrieval_topology))
        profile["retrieval_topology"] = topology_file

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
