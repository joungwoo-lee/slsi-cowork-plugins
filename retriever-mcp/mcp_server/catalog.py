"""MCP tool catalog: name, description, inputSchema for every exposed tool.

Kept as data (not code) so a `tools/list` request stays cheap and so adding
a new tool is just: add an entry here + a function in handlers.py + a row
in handlers.HANDLERS.

All tools are thin wrappers around the hybrid_retriever_windows_local
FastAPI server (RAGFlow-compatible) at $RETRIEVER_BASE_URL.
"""
from __future__ import annotations

from typing import Any

TOOLS: list[dict[str, Any]] = [
    # --- Search / retrieval ---------------------------------------------
    {
        "name": "search",
        "description": (
            "Hybrid retrieval against the running retriever_engine "
            "(SQLite FTS5 keyword + Qdrant local vector). Returns ranked chunks "
            "with document metadata, similarity scores, and a compact citations "
            "array. dataset_ids defaults to RETRIEVER_DEFAULT_DATASETS env if "
            "omitted."
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
                "page": {"type": "integer", "minimum": 1, "default": 1},
                "page_size": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
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
                "rerank_id": {"type": "string", "description": "Optional rerank model id."},
                "pipeline_name": {"type": "string", "description": "Named retrieval pipeline (advanced)."},
                "metadata_condition": {
                    "type": "object",
                    "description": "Server-side metadata filter (forwarded as-is).",
                    "additionalProperties": True,
                },
            },
            "required": ["query"],
        },
    },
    # --- Datasets --------------------------------------------------------
    {
        "name": "list_datasets",
        "description": (
            "List datasets visible to the configured API key. Returns id, name, "
            "description, created_at."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_dataset",
        "description": "Fetch a single dataset's metadata by id.",
        "inputSchema": {
            "type": "object",
            "properties": {"dataset_id": {"type": "string"}},
            "required": ["dataset_id"],
        },
    },
    {
        "name": "create_dataset",
        "description": (
            "Create a new dataset (knowledge base). dataset_id is auto-derived "
            "from name by the server. Note: upload_document also auto-creates a "
            "dataset on first upload, so this is only needed for empty buckets."
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
            "Delete a dataset and ALL its documents/chunks/vectors/files. "
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
            "Upload a single local file to a dataset. The server parses, chunks, "
            "embeds, and indexes synchronously. Creates the dataset auto-magically "
            "if it doesn't exist. Returns the new document_id and chunk stats."
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
                "use_contextual": {
                    "type": "boolean",
                    "description": "Contextual Retrieval (LLM-augmented). Omit to use server default.",
                },
                "pipeline_name": {"type": "string", "description": "Named ingest pipeline (advanced)."},
            },
            "required": ["dataset_id", "file_path"],
        },
    },
    {
        "name": "list_documents",
        "description": "List documents in a dataset (newest first by default).",
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
        "description": "Fetch a single document's metadata (name, chunk counts, ingest config).",
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
            "List the chunks of a document. Useful to inspect how the server "
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
            "Read the ORIGINAL source content of a document from the local file "
            "store (no chunking). Use after `search` to expand a hit into its full "
            "source. Returns content as UTF-8 text when the file is text-like."
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
        "description": "Delete a single document (and its chunks/vectors). Irreversible.",
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
            "List named ingest/retrieval pipelines defined on the server, plus "
            "the configured default and any ingest-profile aliases."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    # --- Diagnostics -----------------------------------------------------
    {
        "name": "health",
        "description": (
            "Hit /health/deep on retriever_engine: verifies keyword backend "
            "(SQLite FTS5), Qdrant local mode, embedding/rerank model config, "
            "and file store. Run first whenever search/upload misbehaves."
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
]
