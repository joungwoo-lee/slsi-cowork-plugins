---
name: rag-search
description: Search from Hybrid Retriever and return contexts/citations. Use when the user asks to query retriever data by question, tune top_n/top_k/vector_similarity_weight/similarity_threshold, or fetch grounded snippets from retriever_engine.
---

# rag-search Skill

Hybrid Retriever의 retrieval API를 호출해 검색 결과를 정형 JSON으로 반환합니다.

## Files
- Script: `scripts/retriever_search.py`
- Optional env file: `retriever.env`

## Required Env
- `RAG_API_KEY` (기본값: `ragflow-key`)
- `RAG_BASE_URL` (기본값: `http://ssai-dev.samsungds.net:9380`)
- `RAG_DATASET_IDS` (기본값: `knowledge-base01`)

Optional:
- `RAG_TIMEOUT` (초, 기본 60)

## Basic Usage example
```bash
python skills/rag-search/scripts/retriever_search.py \
  --query "하이브리드 리트리버 아키텍처 요약" \
  --dataset-ids "sample_knowledge_base01" \
  --top-n 8
```

## Advanced Usage
```bash
python skills/rag-search/scripts/retriever_search.py \
  --query "메모리 임베딩 차원 오류 원인" \
  --dataset-ids "sample_knowledge_base01,user123" \
  --top-k 200 \
  --vector-similarity-weight 0.0 \
  --similarity-threshold 0.0 \
  --page-size 100 \
  --top-n 12
```

## Output Contract
스크립트는 stdout으로 JSON을 출력합니다.

```json
{
  "ok": true,
  "query": "...",
  "base_url": "http://localhost:9380",
  "dataset_ids": ["..."],
  "count": 3,
  "contexts": [
    {
      "text": "...",
      "source": {
        "dataset_id": "...",
        "document_id": "...",
        "document_name": "...",
        "position": 0,
        "chunk_id": "...",
        "similarity": 0.0,
        "vector_similarity": 0.0,
        "term_similarity": 0.0
      }
    }
  ],
  "citations": [
    {
      "document_name": "...",
      "position": 0,
      "score": 0.0,
      "chunk_id": "..."
    }
  ],
  "raw": {}
}
```

실패 시:
```json
{
  "ok": false,
  "error": "...",
  "status": 500,
  "raw_text": "..."
}
```

## Agent Rules
- 사용자가 “리트리버에서 찾아줘/근거 반환해줘”라고 하면 이 스크립트를 사용합니다.
- 사용자 별도 지정 없을 시 기본값은 하기 값을 사용합니다.
  - RAG_BASE_URL= "http://ssai-dev.samsungds.net:9380"
  - RAG_API_KEY= "ragflow-key"
  - RAG_DATASET_IDS= "knowledge-base01"
- 결과 보고 시 `contexts` 핵심 문장 + `citations`를 함께 요약합니다.
- API 에러/타임아웃 시 `ok=false` 원문을 그대로 사용자에게 전달하고 재시도 옵션(top_k/top_n 조정)을 제안합니다.
