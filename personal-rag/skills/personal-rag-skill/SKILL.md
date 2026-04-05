---
name: personal-rag-skill
description: Set up and operate a personal local RAG workflow for SLSI Cowork. Use when installing a self-contained local RAG pipeline, creating a dedicated workspace automatically, uploading files from a watched folder, updating embeddings, or querying a local workspace through the configured MCP server.
---

# Personal RAG Skill

Use this skill to guide a personal local RAG workflow.

## Workflow

1. Run the setup script to install or start the local RAG app and create the dedicated workspace.
2. Drop source files into the configured local RAG folder.
3. Run the update script to upload documents and refresh embeddings.
4. Query the workspace through the configured MCP integration.

## Default Conventions

- App directory: `$HOME/AnythingLLM`
- Local document folder: `$HOME/my_rag_docs`
- Workspace name: `my_rag`
- API base URL: `http://localhost:3001/api`
- Fixed API key: `my-secret-rag-key-2026`

## Bundled Resources

- `scripts/setup_rag.sh`: Install/start the local RAG app, seed API key, and create the workspace.
- `scripts/update_docs.sh`: Upload files from the local folder and trigger embedding refresh.
- `references/concept.md`: Original concept and usage pattern for this workflow.

## Instructions

- Use `scripts/setup_rag.sh` for first-time setup.
- Use `scripts/update_docs.sh` after adding or changing files in `$HOME/my_rag_docs`.
- Query the `my_rag` workspace when the user asks for grounded retrieval from the local document set.
- Keep explanations task-oriented: setup, ingest, then retrieve.
