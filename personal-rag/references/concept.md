# Personal RAG Workflow Concept (Pure Server Version)

This reference captures the current personal local RAG flow based on a non-Docker headless AnythingLLM server deployment.

## Intended Flow

1. **Setup:** Run the integrated setup script once to install dependencies (Node.js, Yarn, Python, jq, sqlite3), clone AnythingLLM, and start both the Collector (8888) and API Server (3001) in the background.
2. **Knowledge Base:** Automatically inject a fixed API key and create the `my_rag` workspace during setup.
3. **Ingestion:** Drop files into `~/my_rag_docs`.
4. **Update:** Run the update script to upload files, parse their server locations using `jq`, and refresh embeddings for the `my_rag` workspace.
5. **Usage:** Query the workspace through the configured MCP connection (AnythingLLM MCP server).

## Deployment Direction

- **Non-Docker Headless Backend:** Directly using the AnythingLLM source tree.
- **Pure Server Logic:** No GUI dependencies, self-contained installation and execution.
- **Automated Pipeline:** Upload -> Location Parsing -> Embedding update in one flow.
