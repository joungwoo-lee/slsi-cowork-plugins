"""MCP tool catalog: name, description, inputSchema for every exposed tool.

The static ``_BASE_TOOLS`` list owns one entry per exposed tool. ``build_tools()``
returns a deep copy of that list with the ``pipeline`` parameter on
``search`` / ``upload_document`` / ``upload_directory`` enriched at call time
with each registered pipeline's name + description, so an agent reading
``tools/list`` can pick the right pipeline without first calling
``list_pipelines``. Adding a new tool is still just: add an entry here + a
function in handlers.py + a row in handlers.HANDLERS.

All tools run in-process against local SQLite FTS5 and optional Qdrant storage.
"""
from __future__ import annotations

import copy
import logging
from typing import Any

logger = logging.getLogger(__name__)

_PIPELINE_AWARE_TOOLS = {"upload", "search"}

# Tools that only make sense as a direct drill-down from another tool.
# Hidden by default; revealed via ``reveal()`` + tools/list_changed when
# the parent tool returns something pointing at them. The parent response
# also echoes a structured ``next_action`` so the model has the exact next
# call even before the refreshed list arrives.
#
# Only flows where the parent's *primary output* doesn't already answer
# the model's likely next question count as a flow-reveal. ``search``
# returns reranked chunks + citations — those *are* the answer, so it has
# no flow follow-up.
_FLOW_REVEALED_TOOLS = {
    "get_job",         # revealed by: upload (async=true) — must poll a job_id
    "list_documents",  # revealed by: list_datasets — drill into a dataset
}

_ADMIN_ONLY_TOOLS = {
    "benchmark_pipelines",
    "create_dataset",
    "delete_dataset",
    "delete_document",
    "get_dataset",            # redundant with list_datasets payload
    "get_document",
    "get_document_content",   # raw original source — niche, not needed after search
    "list_chunks",
    "health",
    "graph_query",
    "start_hippo2_index",
    "list_pipelines",
    "save_pipeline",
    "open_pipeline_editor",
    "get_pipeline_editor",
    "close_pipeline_editor",
    "graph_rebuild",
    "hippo2_index",
    "hippo2_index_document",
    "hippo2_refresh_synonyms",
    "hippo2_search",
    "hippo2_stats",
    "pipeline_tutorial",
}

# Process-wide set of tools dynamically revealed during this MCP session.
# Stdio MCP has a single client per process, so a module-level set is
# sufficient. Cleared on next server start.
_REVEALED: set[str] = set()


def reveal(*names: str) -> bool:
    """Add tools to the visible catalog. Returns True if anything new."""
    added = False
    for name in names:
        if name in _FLOW_REVEALED_TOOLS or name in _ADMIN_ONLY_TOOLS:
            if name not in _REVEALED:
                _REVEALED.add(name)
                added = True
    return added


def reveal_admin() -> bool:
    """Reveal the full admin set + flow tools. Called by admin_help."""
    return reveal(*_FLOW_REVEALED_TOOLS, *_ADMIN_ONLY_TOOLS)


def is_hidden(name: str) -> bool:
    return (name in _ADMIN_ONLY_TOOLS or name in _FLOW_REVEALED_TOOLS) and name not in _REVEALED

_BASE_TOOLS: list[dict[str, Any]] = [
    # --- Search / retrieval ---------------------------------------------
    {
        "name": "search",
        "description": (
            "[Search] Search indexed chunks by question or keywords. Omit dataset_ids "
            "to use RETRIEVER_DEFAULT_DATASETS first; use list_datasets only when no "
            "default dataset is configured or when you need to inspect available "
            "datasets. Returns ranked chunks with document metadata and citations. "
            "The response includes an ``answer_instructions`` string carrying the "
            "active pipeline's per-pipeline answer template — follow it verbatim "
            "when composing the user-facing reply."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural-language or keyword question."},
                "dataset_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Dataset IDs to search. Defaults to RETRIEVER_DEFAULT_DATASETS env.",
                },
                "top_n": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 12,
                    "description": "How many top chunks to return after server-side ranking.",
                },
                "top_k": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 500,
                    "default": 200,
                    "description": "Server-side candidate pool size before paging.",
                },
                "vector_similarity_weight": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "default": 0.5,
                    "description": "0 = keyword only, 1 = vector only.",
                },
                "similarity_threshold": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "default": 0.0,
                    "description": (
                        "Server-side score floor applied to fused similarity "
                        "BEFORE top_n slicing. Chunks with score < threshold "
                        "are dropped; if everything is below the floor the "
                        "response is empty instead of returning weak matches. "
                        "0 disables filtering."
                    ),
                },
                "keyword": {"type": "boolean", "default": True},
                "fusion": {"type": "string", "enum": ["linear", "rrf"], "default": "rrf"},
                "parent_chunk_replace": {"type": "boolean", "default": True},
                "metadata_condition": {
                    "type": "object",
                    "description": "Server-side metadata filter (forwarded as-is).",
                    "additionalProperties": True,
                },
                "pipeline": {
                    "type": "string",
                    "description": (
                        "Named search pipeline profile to override the dataset's "
                        "preferred pipeline. Omit to let the dataset's "
                        "preferred_search_pipeline (set at upload time) decide."
                    ),
                },
            },
            "required": ["query"],
        },
    },
    # --- Datasets --------------------------------------------------------
    {
        "name": "list_datasets",
        "description": (
            "[Dataset] List available datasets. Use this when search cannot fall back "
            "to RETRIEVER_DEFAULT_DATASETS or when you need to inspect choices before "
            "uploading or searching."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_dataset",
        "description": "[Dataset] Fetch one dataset's metadata by id.",
        "inputSchema": {
            "type": "object",
            "properties": {"dataset_id": {"type": "string"}},
            "required": ["dataset_id"],
        },
    },
    {
        "name": "create_dataset",
        "description": (
            "[Dataset] Create a new empty dataset. Usually unnecessary before upload "
            "because upload_document and upload_directory create the dataset "
            "automatically when needed."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "use_when": {"type": "string", "description": "Short guidance for when this dataset should be searched."},
            },
            "required": ["name"],
        },
    },
    {
        "name": "delete_dataset",
        "description": (
            "[Dataset] Delete a dataset and ALL its documents, chunks, vectors, and files. "
            "Irreversible — confirm with the user before calling."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"dataset_id": {"type": "string"}},
            "required": ["dataset_id"],
        },
    },
    # --- Documents -------------------------------------------------------
    {
        "name": "upload",
        "description": (
            "[Ingestion] Upload one file or one directory into a dataset. The server "
            "detects whether path is a file or directory. Defaults to async=true so "
            "large embedding/LLM-backed ingests do not block the MCP request."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "dataset_id": {"type": "string", "description": "Target dataset/knowledge-base id."},
                "path": {"type": "string", "description": "Absolute local file or directory path on the MCP-server host."},
                "async": {"type": "boolean", "default": True, "description": "true = background job, false = synchronous result."},
                "file_extension": {"type": "string", "description": "Optional extension filter when path is a directory."},
                "use_hierarchical": {"type": "string", "enum": ["true", "false", "full"], "description": "Parent-Child chunking. 'full' = full-doc parent. Omit to use server default."},
                "skip_embedding": {"type": "boolean", "default": False},
                "metadata": {"type": "object", "additionalProperties": True},
                "pipeline": {
                    "type": "string",
                    "default": "default",
                    "description": "Named ingest pipeline profile used to define the dataset's indexing behavior.",
                },
            },
            "required": ["dataset_id", "path"],
        },
    },
    {
        "name": "list_documents",
        "description": "[Document] List documents in a dataset, newest first by default.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dataset_id": {"type": "string"},
                "keywords": {"type": "string", "description": "Optional substring filter on document name."},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 30},
                "orderby": {"type": "string", "default": "created_at"},
                "desc": {"type": "boolean", "default": True},
            },
            "required": ["dataset_id"],
        },
    },
    {
        "name": "get_document",
        "description": "[Document] Fetch one document's metadata, including chunk counts and ingest flags.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dataset_id": {"type": "string"},
                "document_id": {"type": "string"},
            },
            "required": ["dataset_id", "document_id"],
        },
    },
    {
        "name": "list_chunks",
        "description": (
            "[Document] List a document's chunks. Useful to inspect how the server "
            "split a file after ingest."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "dataset_id": {"type": "string"},
                "document_id": {"type": "string"},
                "keywords": {"type": "string", "description": "Optional substring filter on chunk content."},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 30},
            },
            "required": ["dataset_id", "document_id"],
        },
    },
    {
        "name": "get_document_content",
        "description": (
            "[Document] Read the original stored source content for one document. "
            "Use this after search when you need the full source rather than chunked "
            "results."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "dataset_id": {"type": "string"},
                "document_id": {"type": "string"},
            },
            "required": ["dataset_id", "document_id"],
        },
    },
    {
        "name": "delete_document",
        "description": "[Document] Delete one document and its chunks/vectors. Irreversible — confirm with the user before calling.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dataset_id": {"type": "string"},
                "document_id": {"type": "string"},
            },
            "required": ["dataset_id", "document_id"],
        },
    },
    # --- Pipelines -------------------------------------------------------
    {
        "name": "list_pipelines",
        "description": (
            "[System] Show the active ingest and retrieval settings exposed by this local server."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "save_pipeline",
        "description": (
            "[System] Create a new pipeline profile (modular combination of components) "
            "and save it to DATA_ROOT/pipelines.json. This allows permanent reuse of "
            "custom RAG configurations."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Unique name for the pipeline profile."},
                "description": {"type": "string", "description": "Brief description of this pipeline's purpose."},
                "indexing_overrides": {
                    "type": "object",
                    "description": "Hypster overrides for indexing (e.g. chunk_chars, use_hierarchical).",
                    "additionalProperties": True,
                },
                "retrieval_overrides": {
                    "type": "object",
                    "description": "Hypster overrides for retrieval (e.g. fusion, top_n).",
                    "additionalProperties": True,
                },
                "search_kwargs": {
                    "type": "object",
                    "description": "Per-call kwargs to force (e.g. vector_similarity_weight, parent_chunk_replace).",
                    "additionalProperties": True,
                },
                "indexing_topology": {
                    "type": ["object", "null"],
                    "description": "Optional full indexing topology from the visual pipeline editor.",
                    "additionalProperties": True,
                },
                "retrieval_topology": {
                    "type": ["object", "null"],
                    "description": "Optional full retrieval topology from the visual pipeline editor.",
                    "additionalProperties": True,
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "open_pipeline_editor",
        "description": (
            "[System] Launch the local visual pipeline editor in a browser. Reuses the "
            "existing editor process when already running and returns its URL."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "preferred_port": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 65535,
                    "default": 8765,
                    "description": "Preferred local port for the editor; falls back to any free port.",
                },
                "open_browser": {
                    "type": "boolean",
                    "default": True,
                    "description": "Open the editor URL in the default browser on this machine.",
                }
            },
        },
    },
    {
        "name": "get_pipeline_editor",
        "description": "[System] Return whether the local visual pipeline editor is running and, if so, its URL and PID.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "close_pipeline_editor",
        "description": "[System] Stop the local visual pipeline editor process if it is running.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    # --- Diagnostics -----------------------------------------------------
    {
        "name": "health",
        "description": (
            "[System] Check local database paths, embedding configuration, and index counts. "
            "Run this first when search or upload misbehaves."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "shallow": {
                    "type": "boolean",
                    "default": False,
                    "description": "Use cheap /health endpoint instead of /health/deep.",
                }
            },
        },
    },
    {
        "name": "admin_help",
        "description": "[Admin] Show hidden maintenance tools and when to use them.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_job",
        "description": "[Job] Fetch one background job's current status, progress, and result/error.",
        "inputSchema": {
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
            "required": ["job_id"],
        },
    },
    # --- Graph (Kùzu embedded) -------------------------------------------
    {
        "name": "graph_query",
        "description": (
            "[Graph] Run a read-only Cypher query over the embedded document graph. "
            "Use this for relationship traversal that normal search cannot answer, "
            "such as neighboring chunks or document fan-out. Call graph_rebuild first "
            "if the graph is stale or empty."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "cypher": {"type": "string", "description": "Read-only Cypher (no CREATE/DELETE/MERGE/SET/DROP/ALTER)."},
                "params": {"type": "object", "description": "Optional named parameters referenced by $name in cypher."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 50},
            },
            "required": ["cypher"],
        },
    },
    {
        "name": "graph_rebuild",
        "description": (
            "[Graph] Rebuild the embedded graph from the canonical SQLite state. Safe "
            "to call after ingesting new documents. Uses Kùzu COPY FROM staged CSVs "
            "so the cost is roughly linear in corpus size, not in chunk count × constant."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    # --- Hippo2 knowledge layer ---------------------------------------
    {
        "name": "hippo2_index",
        "description": (
            "[Hippo2] Build (or refresh) the entity+passage memory graph for a dataset. "
            "Runs LLM-driven OpenIE on every chunk, canonicalises entities, embeds "
            "entities and triples, and rebuilds synonym/context edges. Idempotent — re-running on an "
            "unchanged corpus hits the per-chunk extraction cache. Required before "
            "hippo2_search returns useful results."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "dataset_id": {"type": "string"},
                "rebuild_synonyms": {"type": "boolean", "default": True},
                "max_workers": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 16,
                    "default": 4,
                    "description": "Concurrent LLM extraction workers; respects the LLM client throttle/backoff.",
                },
            },
            "required": ["dataset_id"],
        },
    },
    {
        "name": "start_hippo2_index",
        "description": "[Hippo2 Job] Start a background dataset Hippo2 index job.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dataset_id": {"type": "string"},
                "rebuild_synonyms": {"type": "boolean", "default": True},
                "max_workers": {"type": "integer", "minimum": 1, "maximum": 16, "default": 4},
            },
            "required": ["dataset_id"],
        },
    },
    {
        "name": "hippo2_index_document",
        "description": (
            "[Hippo2] Incremental: re-extract triples for one document's chunks. "
            "Skips synonym rebuild by default so it's safe to call in a tight loop. "
            "Run hippo2_refresh_synonyms once at the end of a batch."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "document_id": {"type": "string"},
                "rebuild_synonyms": {"type": "boolean", "default": False},
            },
            "required": ["document_id"],
        },
    },
    {
        "name": "hippo2_refresh_synonyms",
        "description": (
            "[Hippo2] Rebuild the SYNONYM edges from current entity embeddings. "
            "All-pairs operation — call once after a batch index rather than per "
            "document. Threshold is HIPPO2_SYNONYM_THRESHOLD."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "hippo2_search",
        "description": (
            "[Hippo2] Graph-primary retrieval over fused entity+passage nodes. "
            "Aligns the whole query to embedded triples, seeds matching entities "
            "and passage nodes, runs Personalized PageRank, then applies online "
            "LLM filtering to remove noisy candidates. Use when the question is "
            "about factual memory, relationships, multi-hop context, or associative recall. "
            "Requires hippo2_index to have run."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "dataset_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "top_n": {"type": "integer", "minimum": 1, "maximum": 100, "default": 12},
            },
            "required": ["query"],
        },
    },
    {
        "name": "hippo2_stats",
        "description": "[Hippo2] Inspect passage/entity/triple counts and PPR cache state.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "pipeline_tutorial",
        "description": "[Admin] Show a step-by-step guide on how to create and register a new RAG pipeline.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "benchmark_pipelines",
        "description": (
            "[Admin] Ingest built-in test documents into each pipeline, run 5 predefined queries, "
            "and measure hit rate and latency per pipeline. Returns a JSON report with per-query "
            "results and a markdown summary table. Pipelines requiring external models are "
            "attempted but failures are recorded gracefully."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "pipelines": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Pipeline names to benchmark. Defaults to all registered pipelines. "
                        "Example: [\"default\", \"keyword_only\"]"
                    ),
                },
                "dataset_id_prefix": {
                    "type": "string",
                    "default": "benchmark",
                    "description": "Prefix for ephemeral benchmark dataset IDs (e.g. 'benchmark' → 'benchmark_default').",
                },
                "top_n": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 5,
                    "description": "Number of results to retrieve per query.",
                },
                "cleanup": {
                    "type": "boolean",
                    "default": False,
                    "description": "Delete benchmark datasets after the run. Set true to avoid leaving test data.",
                },
            },
        },
    },
]


def _pipeline_param_description() -> str:
    try:
        from retriever.config import load_config
        from retriever.pipelines import profiles as pipeline_profiles
    except Exception as exc:  # noqa: BLE001
        logger.debug("pipeline registry unavailable: %s", exc)
        return "Named ingest pipeline profile."
    try:
        cfg = load_config()
        pipeline_profiles.sync_with_disk(cfg)
        entries = pipeline_profiles.describe()
    except Exception as exc:  # noqa: BLE001
        logger.debug("pipeline registry sync failed: %s", exc)
        return "Named ingest pipeline profile."
    lines = ["Named ingest pipeline profile. This is recorded onto the dataset during ingest."]
    for entry in entries:
        name = entry.get("name") or ""
        desc = (entry.get("description") or "").strip()
        if name:
            lines.append(f"- '{name}': {desc}" if desc else f"- '{name}'")
    return "\n".join(lines)


def _pipeline_enum() -> list[str] | None:
    try:
        from retriever.config import load_config
        from retriever.pipelines import profiles as pipeline_profiles
    except Exception:
        return None
    try:
        cfg = load_config()
        pipeline_profiles.sync_with_disk(cfg)
        names = pipeline_profiles.names()
    except Exception:
        return None
    return names or None


def _dataset_entries() -> list[dict[str, str]]:
    try:
        from retriever.config import load_config
        from retriever import storage
    except Exception:
        return []
    try:
        cfg = load_config()
        with storage.sqlite_session(cfg) as conn:
            rows = conn.execute(
                "SELECT dataset_id, name, description, metadata_json FROM datasets ORDER BY created_at DESC"
            ).fetchall()
    except Exception as exc:
        logger.debug("dataset registry unavailable: %s", exc)
        return []
    out: list[dict[str, str]] = []
    for dataset_id, name, description, metadata_json in rows:
        use_when = ""
        try:
            import json
            meta = json.loads(metadata_json or "{}") or {}
            use_when = str(meta.get("use_when") or "").strip()
        except Exception:
            use_when = ""
        out.append({
            "id": str(dataset_id or ""),
            "name": str(name or dataset_id or ""),
            "description": str(description or ""),
            "use_when": use_when,
        })
    return out


def _dataset_param_description(is_many: bool) -> str:
    entries = _dataset_entries()
    head = (
        "Dataset IDs to search. Choose the dataset whose recorded 'use when' note best matches the request."
        if is_many
        else "Target dataset id. Choose the dataset whose recorded 'use when' note best matches the request."
    )
    if not entries:
        return head
    lines = [head, "Available datasets:"]
    for item in entries:
        label = item["id"]
        use_when = item["use_when"] or item["description"] or "No usage note recorded."
        lines.append(f"- '{label}': {use_when}")
    return "\n".join(lines)


def _dataset_enum() -> list[str] | None:
    entries = _dataset_entries()
    names = [item["id"] for item in entries if item["id"]]
    return names or None


def build_tools() -> list[dict[str, Any]]:
    """Return the tool catalog with dataset guidance enriched.

    Called every time the server handles ``tools/list``, so newly-saved
    datasets show up immediately without restarting the MCP server.
    """
    dataset_description_single = _dataset_param_description(False)
    dataset_description_many = _dataset_param_description(True)
    dataset_enum = _dataset_enum()
    pipeline_description = _pipeline_param_description()
    pipeline_enum = _pipeline_enum()
    tools = [tool for tool in copy.deepcopy(_BASE_TOOLS) if not is_hidden(tool.get("name", ""))]
    for tool in tools:
        props = tool.get("inputSchema", {}).get("properties", {})
        if tool.get("name") in _PIPELINE_AWARE_TOOLS:
            param = props.get("pipeline")
            if isinstance(param, dict):
                param["description"] = pipeline_description
                if pipeline_enum:
                    param["enum"] = pipeline_enum
        ds_one = props.get("dataset_id")
        if isinstance(ds_one, dict):
            ds_one["description"] = dataset_description_single
            if dataset_enum:
                ds_one["enum"] = dataset_enum
        ds_many = props.get("dataset_ids")
        if isinstance(ds_many, dict):
            ds_many["description"] = dataset_description_many
            items = ds_many.get("items")
            if isinstance(items, dict) and dataset_enum:
                items["enum"] = dataset_enum
    return tools


# Kept for backwards-compatibility: import sites that grabbed ``TOOLS`` at
# import time still work, but ``handle_tools_list`` should call
# ``build_tools()`` so descriptions reflect runtime-added profiles.
TOOLS = _BASE_TOOLS
