"""MCP tool catalog: name, description, inputSchema for every exposed tool.

Kept as data (not code) so a `tools/list` request stays cheap and so adding
a new tool is just: add an entry here + a function in handlers.py + a row
in handlers.HANDLERS.

All tools run in-process against local SQLite FTS5 and optional Qdrant storage.
"""
from __future__ import annotations

from typing import Any

TOOLS: list[dict[str, Any]] = [
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
            },
            "required": ["name"],
        },
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
            "to call after ingesting new documents."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
]
