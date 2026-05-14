"""MCP tool catalog: name, description, inputSchema for every exposed tool.

Kept as data (not code) so a `tools/list` request stays cheap and so adding
a new tool is just: add an entry here + a function in handlers.py + a row
in handlers.HANDLERS.
"""
from __future__ import annotations

from typing import Any

TOOLS: list[dict[str, Any]] = [
    # --- Search & retrieval ---------------------------------------------
    {
        "name": "search",
        "description": (
            "Primary tool for any request to find something in email, mail, Outlook mailboxes, "
            "or a PST archive. Use this instead of generic filesystem or text-search tools when "
            "the user is asking about messages. Hybrid search over an ingested PST archive: "
            "SQLite FTS5 (keyword) + Qdrant (semantic) with score fusion. Optional sender/date "
            "filters are applied first to form the candidate mail set, then keyword/semantic "
            "search runs only inside that filtered set. Returns ranked mail metadata (subject, "
            "sender, received, score, snippet, body_path). Read body_path with the read_mail "
            "tool to get the unified body+attachments markdown."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language or keyword query, e.g. '출장비 정산', 'budget review', or 'find the mail about server outage'.",
                },
                "sender_like": {
                    "type": "string",
                    "description": "Only search mails whose sender contains this case-insensitive substring. Example: 'kim' or 'naver.com'.",
                },
                "sender_not_like": {
                    "type": "string",
                    "description": "Exclude mails whose sender contains this case-insensitive substring. Example: 'noreply' or 'notification'.",
                },
                "sender_exact": {
                    "type": "string",
                    "description": "Only search mails whose sender exactly matches this string. Use this when you know the exact sender value.",
                },
                "received_from": {
                    "type": "string",
                    "description": "Only search mails received on or after this ISO-8601 timestamp. Example: '2026-01-01T00:00:00+00:00'.",
                },
                "received_to": {
                    "type": "string",
                    "description": "Only search mails received on or before this ISO-8601 timestamp. Example: '2026-12-31T23:59:59+00:00'.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["hybrid", "keyword", "semantic"],
                    "default": "hybrid",
                    "description": "hybrid combines FTS5 + Qdrant inside the filtered candidate set; keyword-only or semantic-only also available.",
                },
                "top": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_mails",
        "description": (
            "Use this when the user wants to browse or enumerate emails rather than search by "
            "topic, such as 'show recent mails', 'list mails from Alice', or 'browse messages "
            "with this subject'. Lists indexed mails from the SQLite metadata table, newest "
            "first. Supports substring filters on sender / subject and offset-based pagination. "
            "Call the exact tool name `list_mails` (some clients may expose the namespaced form "
            "`email_mcp_list_mails`), and never insert whitespace inside the tool name."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sender_like": {"type": "string", "description": "Case-insensitive substring filter on sender."},
                "subject_like": {"type": "string", "description": "Case-insensitive substring filter on subject."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 50},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
            },
        },
    },
    {
        "name": "read_mail",
        "description": (
            "Use this only after search/list_mails identified a specific candidate that needs "
            "deeper inspection. Reads the unified body.md (mail body + every attachment "
            "converted to markdown, in one file) for a given mail_id as returned by `search` / "
            "`list_mails`. Returns the file's full UTF-8 contents."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"mail_id": {"type": "string"}},
            "required": ["mail_id"],
        },
    },
    {
        "name": "read_meta",
        "description": (
            "Return the per-mail meta.json (subject, sender, recipients, received, "
            "folder_path, mail_id) without loading body.md. Cheaper than read_mail when "
            "the caller only needs headers."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"mail_id": {"type": "string"}},
            "required": ["mail_id"],
        },
    },
    {
        "name": "read_attachment",
        "description": (
            "Inspect a mail's attachments. With only `mail_id` set, returns the list of "
            "attachment filenames + sizes. With `filename` set, returns the absolute path, "
            "size, and content-type guess for that single file (the caller can then open "
            "it directly — the file lives on the same machine as the MCP server)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "mail_id": {"type": "string"},
                "filename": {
                    "type": "string",
                    "description": "Exact filename inside the mail's attachments/ folder. Omit to list.",
                },
            },
            "required": ["mail_id"],
        },
    },
    {
        "name": "stats",
        "description": (
            "Counts and paths describing the current index: total mails in SQLite, how many "
            "have a Qdrant vector, files_root mail-folder count, db / vectorDB paths. Use "
            "to verify ingest progress without running search."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    # --- Pipeline (write side) ------------------------------------------
    {
        "name": "convert",
        "description": (
            "Phase 1 only: PST → per-mail body.md + meta.json + original-extension "
            "attachments under DATA_ROOT/Files/. Does NOT touch SQLite or Qdrant. Useful "
            "for inspecting markdown output before committing to indexing. `limit` is "
            "REQUIRED here so MCP clients don't time out — for full PSTs use the CLI: "
            "`py -3.9 scripts\\convert.py`."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "description": "Max messages to convert."},
                "pst": {"type": "string", "description": "Override PST path. Default: PST_PATH from .env."},
            },
            "required": ["limit"],
        },
    },
    {
        "name": "index",
        "description": (
            "Phase 2 only: read already-converted mail folders and index them into SQLite "
            "FTS5 (always) + Qdrant (unless skip_embedding). Does NOT re-decode the PST. "
            "Pass `mail_ids` to re-index just specific mails — useful after switching "
            "embedding model / dimension."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "skip_embedding": {
                    "type": "boolean",
                    "default": False,
                    "description": "Build SQLite FTS5 only; skip embedding API + Qdrant.",
                },
                "mail_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Index only these mail_ids (default: every folder under Files/).",
                },
            },
        },
    },
    {
        "name": "ingest",
        "description": (
            "Convenience wrapper: convert (Phase 1) + index (Phase 2) in one call. "
            "LONG-RUNNING — `limit` is REQUIRED; for a full PST use the CLI: "
            "`py -3.9 scripts\\ingest.py`."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "description": "Max messages to process this run."},
                "skip_embedding": {"type": "boolean", "default": False},
                "skip_convert": {"type": "boolean", "default": False, "description": "Reuse existing Files/."},
                "skip_index": {"type": "boolean", "default": False, "description": "Convert only; don't index."},
                "pst": {"type": "string", "description": "Override PST path."},
            },
            "required": ["limit"],
        },
    },
    # --- Diagnostics -----------------------------------------------------
    {
        "name": "doctor",
        "description": (
            "Diagnose the email-connector install: Python 3.9 + 64-bit, Windows platform, "
            "every dep importable, .env present and populated, PST_PATH reachable, "
            "DATA_ROOT writable, embedding API reachable with the configured headers. "
            "Returns {all_ok, checks[]}. Run this first when anything fails."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "skip_api": {"type": "boolean", "default": False, "description": "Skip the embedding API ping."},
                "skip_pst": {"type": "boolean", "default": False, "description": "Skip the PST_PATH existence check."},
            },
        },
    },
    # --- Graph (Kùzu embedded) -------------------------------------------
    {
        "name": "graph_query",
        "description": (
            "Run a read-only Cypher query against the embedded Kùzu property graph "
            "of mails and people. Schema: Mail(id,subject,received,folder_path), "
            "Person(address); edges (Person)-[:SENT]->(Mail), "
            "(Person)-[:RECEIVED]->(Mail). Use for relationship questions BM25/"
            "vector search cannot answer (e.g. all mails from one sender, "
            "co-recipient graphs). Call graph_rebuild first if the graph is stale."
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
            "Wipe and re-populate the embedded Kùzu graph from mail_metadata. "
            "Idempotent. Returns {mails, people, edges}."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
]
