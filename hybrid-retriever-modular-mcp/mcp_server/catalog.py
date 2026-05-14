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
            "Hybrid retrieval against the local retriever index "
            "(SQLite FTS5 keyword + optional Qdrant local vector). Returns ranked chunks "
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
                "fusion": {"type": "string", "enum": ["linear", "rrf"], "default": "linear"},
                "parent_chunk_replace": {"type": "boolean", "default": True},
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
            "Upload a single local text file to a dataset. The MCP parses, chunks, "
            "embeds when configured, and indexes synchronously. Creates the dataset automatically "
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
                "skip_embedding": {"type": "boolean", "default": False},
                "metadata": {
                    "type": "object",
                    "description": "Optional document metadata stored with every chunk.",
                    "additionalProperties": True,
                },
            },
            "required": ["dataset_id", "file_path"],
        },
    },
    {
        "name": "upload_directory",
        "description": (
            "Recursively upload all supported files in a local directory to a dataset. "
            "The MCP parses, chunks, embeds, and indexes each file synchronously. "
            "Returns a summary of uploaded documents and any errors."
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
                "use_contextual": {
                    "type": "boolean",
                    "description": "Contextual Retrieval (LLM-augmented). Omit to use server default.",
                },
                "skip_embedding": {"type": "boolean", "default": False},
                "metadata": {
                    "type": "object",
                    "description": "Optional shared metadata stored with every chunk in the directory.",
                    "additionalProperties": True,
                },
            },
            "required": ["dataset_id", "dir_path"],
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
            "Verify local SQLite FTS5 database, data root, optional embedding config, "
            "and index counts. Run first whenever search/upload misbehaves."
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
            "Run a read-only Cypher query against the embedded Kùzu property graph. "
            "Schema: nodes Dataset(id,name), Document(id,name,dataset_id,source_path), "
            "Chunk(id,document_id,dataset_id,position); edges "
            "(Document)-[:IN_DATASET]->(Dataset), (Document)-[:HAS_CHUNK]->(Chunk), "
            "(Chunk)-[:NEXT]->(Chunk). Use this for relationship traversal that BM25/"
            "vector search cannot answer (e.g. neighbouring chunks, all docs in a "
            "dataset, document fan-out). Call graph_rebuild first if the graph is "
            "stale or empty."
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
            "Wipe and re-populate the embedded Kùzu graph from the canonical SQLite "
            "state (datasets/documents/chunks). Idempotent and safe to call after "
            "ingesting new documents. Returns counts."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
]
