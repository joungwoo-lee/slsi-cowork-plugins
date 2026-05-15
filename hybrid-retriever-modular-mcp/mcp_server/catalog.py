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

# Tools whose `pipeline` parameter description should be enriched with the
# list of registered pipelines at tools/list time.
_PIPELINE_AWARE_TOOLS = {"search", "upload_document", "upload_directory", "start_upload_document", "start_upload_directory"}

_BASE_TOOLS: list[dict[str, Any]] = [
    # --- Search / retrieval ---------------------------------------------
    {
        "name": "search",
        "description": (
            "[Search] Search indexed chunks by question or keywords. Omit dataset_ids "
            "to use RETRIEVER_DEFAULT_DATASETS first; use list_datasets only when no "
            "default dataset is configured or when you need to inspect available "
            "datasets. Returns ranked chunks with document metadata and citations."
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
                },
                "keyword": {"type": "boolean", "default": True},
                "fusion": {"type": "string", "enum": ["linear", "rrf"], "default": "linear"},
                "parent_chunk_replace": {"type": "boolean", "default": True},
                "metadata_condition": {
                    "type": "object",
                    "description": "Server-side metadata filter (forwarded as-is).",
                    "additionalProperties": True,
                },
                "pipeline": {
                    "type": "string",
                    "default": "default",
                    "description": "Named pipeline profile (see list_pipelines.profiles). 'default' = legacy hybrid; alternative profiles change fusion/embedding behavior.",
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
        "name": "upload_document",
        "description": (
            "[Ingestion] Upload one local file into a dataset. Supports TXT, MD, PDF, "
            "DOCX, XLSX, and CSV. Parses, chunks, and indexes synchronously; creates "
            "the dataset automatically if it does not exist."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "dataset_id": {"type": "string", "description": "Target dataset/knowledge-base id."},
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to a local file on the MCP-server host.",
                },
                "use_hierarchical": {
                    "type": "string",
                    "enum": ["true", "false", "full"],
                    "description": "Parent-Child chunking. 'full' = full-doc parent. Omit to use server default.",
                },
                "skip_embedding": {"type": "boolean", "default": False},
                "metadata": {
                    "type": "object",
                    "description": "Optional document metadata stored with every chunk.",
                    "additionalProperties": True,
                },
                "pipeline": {
                    "type": "string",
                    "default": "default",
                    "description": "Named pipeline profile (see list_pipelines.profiles).",
                },
                "auto_hipporag": {
                    "type": "boolean",
                    "default": False,
                    "description": "Run HippoRAG OpenIE on the uploaded chunks immediately after ingest. Requires LLM_API_URL and EMBEDDING_API_URL. Skips synonym rebuild (run hipporag_refresh_synonyms at the end of a batch).",
                },
            },
            "required": ["dataset_id", "file_path"],
        },
    },
    {
        "name": "start_upload_document",
        "description": (
            "[Ingestion Job] Start a background upload of one local file into a dataset. "
            "Use this instead of upload_document for slow embedding/LLM-backed ingest."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "dataset_id": {"type": "string", "description": "Target dataset/knowledge-base id."},
                "file_path": {"type": "string", "description": "Absolute path to a local file on the MCP-server host."},
                "use_hierarchical": {"type": "string", "enum": ["true", "false", "full"]},
                "skip_embedding": {"type": "boolean", "default": False},
                "metadata": {"type": "object", "additionalProperties": True},
                "pipeline": {"type": "string", "default": "default", "description": "Named pipeline profile (see list_pipelines.profiles)."},
                "auto_hipporag": {"type": "boolean", "default": False},
            },
            "required": ["dataset_id", "file_path"],
        },
    },
    {
        "name": "upload_directory",
        "description": (
            "[Ingestion] Upload all supported files in a local directory into a dataset. "
            "Use this for bulk ingest; it walks the directory recursively and indexes "
            "each supported file synchronously."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "dataset_id": {"type": "string", "description": "Target dataset/knowledge-base id."},
                "dir_path": {
                    "type": "string",
                    "description": "Absolute path to a local directory on the MCP-server host.",
                },
                "file_extension": {
                    "type": "string",
                    "description": "Optional specific extension to filter by (e.g. '.md' or '.pdf'). If omitted, processes all supported text/document files.",
                },
                "use_hierarchical": {
                    "type": "string",
                    "enum": ["true", "false", "full"],
                    "description": "Parent-Child chunking. 'full' = full-doc parent. Omit to use server default.",
                },
                "skip_embedding": {"type": "boolean", "default": False},
                "metadata": {
                    "type": "object",
                    "description": "Optional shared metadata stored with every chunk in the directory.",
                    "additionalProperties": True,
                },
                "pipeline": {
                    "type": "string",
                    "default": "default",
                    "description": "Named pipeline profile (see list_pipelines.profiles).",
                },
                "auto_hipporag": {
                    "type": "boolean",
                    "default": False,
                    "description": "Run HippoRAG OpenIE + synonym rebuild after the bulk ingest. Requires LLM_API_URL and EMBEDDING_API_URL. Skips per-document synonym work and consolidates it once at the end of the batch.",
                },
            },
            "required": ["dataset_id", "dir_path"],
        },
    },
    {
        "name": "start_upload_directory",
        "description": (
            "[Ingestion Job] Start a background upload of all supported files in a local "
            "directory. Use this instead of upload_directory for large folders."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "dataset_id": {"type": "string", "description": "Target dataset/knowledge-base id."},
                "dir_path": {"type": "string", "description": "Absolute path to a local directory on the MCP-server host."},
                "file_extension": {"type": "string"},
                "use_hierarchical": {"type": "string", "enum": ["true", "false", "full"]},
                "skip_embedding": {"type": "boolean", "default": False},
                "metadata": {"type": "object", "additionalProperties": True},
                "pipeline": {"type": "string", "default": "default", "description": "Named pipeline profile (see list_pipelines.profiles)."},
                "auto_hipporag": {"type": "boolean", "default": False},
            },
            "required": ["dataset_id", "dir_path"],
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
    # --- HippoRAG knowledge layer ---------------------------------------
    {
        "name": "hipporag_index",
        "description": (
            "[HippoRAG] Build (or refresh) the entity knowledge graph for a dataset. "
            "Runs LLM-driven OpenIE on every chunk, canonicalises entities, embeds "
            "them, and rebuilds the synonym edges. Idempotent — re-running on an "
            "unchanged corpus hits the per-chunk extraction cache. Required before "
            "hipporag_search returns useful results."
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
        "name": "start_hipporag_index",
        "description": "[HippoRAG Job] Start a background dataset HippoRAG index job.",
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
        "name": "hipporag_index_document",
        "description": (
            "[HippoRAG] Incremental: re-extract triples for one document's chunks. "
            "Skips synonym rebuild by default so it's safe to call in a tight loop. "
            "Run hipporag_refresh_synonyms once at the end of a batch."
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
        "name": "hipporag_refresh_synonyms",
        "description": (
            "[HippoRAG] Rebuild the SYNONYM edges from current entity embeddings. "
            "All-pairs operation — call once after a batch index rather than per "
            "document. Threshold is HIPPORAG_SYNONYM_THRESHOLD."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "hipporag_search",
        "description": (
            "[HippoRAG] Graph-primary retrieval. Extracts query entities via LLM, "
            "links them to graph entities by embedding similarity, runs Personalized "
            "PageRank from those seeds, and aggregates the rank back to chunks. Use "
            "when the question is about relationships, multi-hop facts, or when "
            "plain hybrid search misses passages that share linked entities. "
            "Requires hipporag_index to have run."
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
        "name": "hipporag_stats",
        "description": (
            "[HippoRAG] Report entity/triple/mention/synonym counts and PPR engine "
            "warmth (cached matrix size + checksum). Run before/after indexing to "
            "verify state."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _pipeline_param_description() -> str:
    """Build the ``pipeline`` schema description from the live pipeline registry.

    The retriever package is imported lazily so this module stays importable
    even when its heavyweight optional deps (haystack et al) are still being
    installed by ``boot_doctor``.
    """
    try:
        from retriever.config import load_config
        from retriever.pipelines import profiles as pipeline_profiles
    except Exception as exc:  # noqa: BLE001 — boot-time deps not ready yet
        logger.debug("pipeline registry unavailable: %s", exc)
        return (
            "Named pipeline profile. Call list_pipelines to see available "
            "profiles and their use-cases."
        )

    try:
        cfg = load_config()
        pipeline_profiles.sync_with_disk(cfg)
        entries = pipeline_profiles.describe()
    except Exception as exc:  # noqa: BLE001 — never break tools/list
        logger.debug("pipeline registry sync failed: %s", exc)
        return (
            "Named pipeline profile. Call list_pipelines to see available "
            "profiles and their use-cases."
        )

    lines = [
        "Named pipeline profile. Pick the one whose 'Use when' clause best "
        "matches the query (default = general-purpose hybrid)."
    ]
    for entry in entries:
        name = entry.get("name") or ""
        desc = (entry.get("description") or "").strip()
        if not name:
            continue
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


def build_tools() -> list[dict[str, Any]]:
    """Return the tool catalog with the pipeline parameter enriched.

    Called every time the server handles ``tools/list``, so newly-saved
    profiles show up immediately without restarting the MCP server.
    """
    description = _pipeline_param_description()
    enum = _pipeline_enum()
    tools = copy.deepcopy(_BASE_TOOLS)
    for tool in tools:
        if tool.get("name") not in _PIPELINE_AWARE_TOOLS:
            continue
        props = tool.get("inputSchema", {}).get("properties", {})
        param = props.get("pipeline")
        if not isinstance(param, dict):
            continue
        param["description"] = description
        if enum:
            param["enum"] = enum
    return tools


# Kept for backwards-compatibility: import sites that grabbed ``TOOLS`` at
# import time still work, but ``handle_tools_list`` should call
# ``build_tools()`` so descriptions reflect runtime-added profiles.
TOOLS = _BASE_TOOLS
