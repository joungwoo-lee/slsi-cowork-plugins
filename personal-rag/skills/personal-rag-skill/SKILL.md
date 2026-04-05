---
name: personal-rag-skill
description: Operate a personal local RAG workflow through a Docker-based local server and MCP connection. Use when a user wants to initialize the personal RAG server, ingest files from the personal document folder, refresh embeddings, or retrieve grounded answers from the local workspace.
---

# Personal RAG Skill

Follow this skill when the user asks to use or manage the personal local RAG workflow.

## Action Rules

- For first-time setup or reset requests, run `scripts/setup_rag.sh`.
- For document ingestion or refresh requests, run `scripts/update_docs.sh`.
- For retrieval requests, use the configured MCP server against the `my_rag` workspace.
- Keep responses grounded in retrieved workspace content when answering questions from indexed files.

## Default Operating Values

- Document folder: `$HOME/my_rag_docs`
- Server URL: `http://localhost:3001`
- Workspace: `my_rag`
- Storage path: `$HOME/personal-rag/storage`

## Resource Usage

- Read `../../docs/server-mode.md` when you need deployment context.
- Read `../../references/concept.md` only if you need the original workflow intent.
- Execute `../../scripts/setup_rag.sh` for Docker-based initialization.
- Execute `../../scripts/update_docs.sh` for upload + embedding refresh.

## Response Pattern

- If setup is missing, say setup is required and run or recommend the setup step.
- If files changed, run the update step before retrieval.
- When answering from retrieved content, summarize clearly and cite which local workspace was queried.
- Do not explain internal design unless the user asks.
