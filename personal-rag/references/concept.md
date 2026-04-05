# Personal RAG Workflow Concept

This reference captures the original concept behind the personal local RAG flow.

## Intended Flow

1. Run setup once.
2. Drop files into `~/my_rag_docs`.
3. Run the update script to upload files and refresh embeddings.
4. Query workspace `my_rag` through the configured MCP connection.

## Current Deployment Direction

The workflow now uses a server-style Docker deployment instead of a desktop AppImage flow so it can operate in headless environments.
