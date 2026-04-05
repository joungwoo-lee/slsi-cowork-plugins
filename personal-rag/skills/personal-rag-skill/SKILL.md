---
name: personal-rag-skill
description: |
  Search and answer questions grounded in the user's local document folder ($HOME/my_rag_docs).
  Trigger when the user says: "문서 참고해서", "폴더 안의 문서 기반으로", "내 문서에서 찾아줘",
  "RAG 검색", "로컬 문서 검색", "my_rag_docs 참고", or any request that references
  personal/local documents for grounded retrieval answers.
  Also use for RAG backend setup, document ingestion, and embedding refresh.
---

# Personal RAG Skill

Follow this skill when the user asks questions that should be answered from their local document folder,
or when they want to manage the personal RAG pipeline (setup / ingest / search).

## Auto Retrieval Flow (default)

When the user asks a question referencing local documents:

1. **Freshness check** — run `scripts/check_and_ingest.sh` to detect new/changed files and auto-ingest them.
2. **Vector search** — run `python3 scripts/rag_search.py --query "<user question>" --top-n 5`.
3. **Answer** — summarize the retrieved `contexts`, cite `citations` (document title + similarity score).

## Action Rules

- First-time setup or reset → run `scripts/setup_rag.sh`.
- Explicit ingest/refresh request → run `scripts/update_docs.sh`.
- Question or retrieval request → run the **Auto Retrieval Flow** above.
- Keep responses grounded in retrieved content. If no relevant results, say so clearly.

## Default Operating Values

- App directory: `$HOME/anythingllm-server`
- Document folder: `$HOME/my_rag_docs`
- Server URL: `http://localhost:3001`
- Workspace: `my_rag`
- DB path: `$HOME/anythingllm-server/server/storage/anythingllm.db`
- LanceDB path: `$HOME/anythingllm-server/server/storage/lancedb`
- Fixed API key: `my-secret-rag-key-2026`
- Embedding model: `all-MiniLM-L6-v2` (384-dim, cosine distance)

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/setup_rag.sh` | One-time headless AnythingLLM server setup |
| `scripts/update_docs.sh` | Upload all docs from `$HOME/my_rag_docs` and embed |
| `scripts/check_and_ingest.sh` | Detect new/changed files only, ingest incrementally |
| `scripts/rag_search.py` | Vector similarity search against LanceDB |

## Search Usage

```bash
# Basic search
python3 scripts/rag_search.py --query "검색할 질문" --top-n 5

# With similarity threshold filter
python3 scripts/rag_search.py --query "기술 스택" --top-n 8 --threshold 0.2
```

## Response Pattern

- If server is not running, start it first or recommend setup.
- If new files detected, ingest before searching.
- Summarize retrieved content clearly and cite document titles.
- Do not explain internal design unless the user asks.
