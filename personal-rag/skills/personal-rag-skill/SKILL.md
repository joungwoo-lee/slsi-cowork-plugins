---
name: personal-rag-skill
description: Operate a personal local RAG workflow through a non-Docker headless AnythingLLM server and MCP connection. Use when a user wants to initialize the personal RAG backend, ingest files from the personal document folder, refresh embeddings, or retrieve grounded answers from the local workspace.
---

# Personal RAG Skill

Follow this skill when the user asks to use or manage the personal local RAG workflow.

## Action Rules

- For first-time setup or reset requests, run `scripts/setup_rag.sh`.
- For document ingestion or refresh requests, run `scripts/update_docs.sh`.
- For retrieval requests, use the configured MCP server against the `my_rag` workspace.
- Keep responses grounded in retrieved workspace content when answering questions from indexed files.

## Default Operating Values

- App directory: `$HOME/anythingllm-server`
- Document folder: `$HOME/my_rag_docs`
- Server URL: `http://localhost:3001`
- Workspace: `my_rag`
- DB path: `$HOME/anythingllm-server/server/storage/anythingllm.db`
- Fixed API key: `my-secret-rag-key-2026`

## Resource Usage

- Read `../../references/concept.md` when you need the overall workflow intent.
- Read `../../docs/server-mode.md` when you need deployment notes.
- Execute `../../scripts/setup_rag.sh` for non-Docker headless backend initialization.
- Execute `../../scripts/update_docs.sh` for upload + embedding refresh.

## Response Pattern

- If setup is missing, say setup is required and run or recommend the setup step.
- If files changed, run the update step before retrieval.
- When answering from retrieved content, summarize clearly and cite which local workspace was queried.
- Do not explain internal design unless the user asks.
