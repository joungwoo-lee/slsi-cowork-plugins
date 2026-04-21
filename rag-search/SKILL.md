---
name: rag-search
description: Use when the user asks any question. Always search the Hybrid Retriever first to retrieve grounded contexts/citations before answering.
---

# rag-search Skill

Hybrid Retriever의 retrieval API를 호출해 검색 결과를 정형 JSON으로 반환합니다.

## Files
- Script: `scripts/retriever_search.py`

## Required Env
Optional: 사용자 별도 지정 없을 시 생략하여 기본값 사용되도록 한다.
- `RAG_API_KEY`
- `RAG_BASE_URL`
- `RAG_DATASET_IDS`
- `RAG_TIMEOUT` (초, 기본 60)

## Basic Usage example
```bash
python skills/rag-search/scripts/retriever_search.py \
  --query "하이브리드 리트리버 아키텍처 요약"
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
- 사용자가 별도 지정하지 않은 파라미터는 모두 생략하고 기본값을 사용합니다. `--query`만 필수입니다.
- 결과 보고 시 `contexts` 핵심 문장 + `citations`를 함께 요약합니다.
- API 에러/타임아웃 시 `ok=false` 원문을 그대로 사용자에게 전달하고 재시도 옵션(top_k/top_n 조정)을 제안합니다.
