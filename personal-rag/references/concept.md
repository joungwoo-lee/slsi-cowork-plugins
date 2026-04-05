# Personal RAG Workflow Concept

This reference captures the current personal local RAG flow.

## Intended Flow

1. Run the non-Docker headless server setup once.
2. Drop files into `~/my_rag_docs`.
3. Run the update script to upload files and refresh embeddings.
4. Query workspace `my_rag` through the configured MCP connection.

## Deployment Direction

The workflow uses a non-Docker headless backend deployment based on the AnythingLLM server source tree.
It avoids desktop AppImage startup and does not depend on Docker container execution.
