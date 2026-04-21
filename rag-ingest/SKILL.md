---
name: rag-ingest
description: Upload files to Hybrid Retriever and trigger chunk/embedding ingest. Use when the user asks to ingest file into retriever, create/update a dataset.
---

# rag-ingest Skill

Hybrid Retriever의 문서 업로드 + 파싱(청킹/임베딩)까지 한 번에 수행합니다.

## Files
- Script: `scripts/retriever_ingest.py`

## Required Env
Optional: 사용자 별도 지정 없을 시 생략하여 기본값 사용되도록 한다.
- `RAG_API_KEY`
- `RAG_BASE_URL`
- `RAG_DATASET_IDS`
- `RAG_TIMEOUT` (초, 기본 60)

## Basic Usage example
```bash
python skills/rag-ingest/scripts/retriever_ingest.py \
  --file-path "/tmp/sample.txt"
```

## Chunking Mode Options
```bash
python skills/rag-ingest/scripts/retriever_ingest.py \
  --file-path "/tmp/sample.txt" \
  --dataset-id "sample_knowledge_base01" \
  --use-hierarchical true \
  --use-contextual false
```

- `--use-hierarchical` / `--use-contextual`
  - `true|false|none` 지원
  - `none`이면 서버 설정 따름

## Output Contract
성공:
```json
{
  "ok": true,
  "base_url": "http://localhost:9380",
  "dataset_id": "sample_knowledge_base01",
  "file_path": "/tmp/sample.txt",
  "uploaded_doc_id": "...",
  "parse_response": {"code":0, "message":"success", "data":{...}}
}
```

실패:
```json
{
  "ok": false,
  "error": "...",
  "status": 500,
  "raw_text": "..."
}
```

## Agent Rules
- 사용자가 파일 ingest를 요청하면 이 스크립트를 먼저 사용합니다.
- 사용자가 별도 지정하지 않은 파라미터는 모두 생략하고 기본값을 사용합니다. `--file-path`만 필수입니다.
- 업로드 성공 후 반드시 parse/chunks API까지 호출해 인덱싱 시작 상태를 확인합니다.
- 실패 시 HTTP status와 raw_text를 사용자에게 그대로 전달합니다.
