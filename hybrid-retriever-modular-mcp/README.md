# hybrid-retriever-modular-mcp

자체 완결형 로컬 RAG MCP 서버. `py server.py`가 stdio MCP를 띄우고, 도구 호출은 in-process로 **SQLite FTS5 (kiwipiepy 한국어 형태소) + 선택적 Qdrant 벡터 + 임베디드 Kùzu 그래프**를 사용합니다. 별도 백엔드 불필요.

## 도구 노출

`tools/list`는 **공개 8개만** 노출합니다. 컨텍스트 비용·라우팅 정확도 양쪽에 유리합니다. 그 외 도구는 `admin_help`로 카탈로그를 끌어와 `tools/call`로 바로 호출합니다.

| 공개 | 역할 |
|---|---|
| `search` | dataset metadata가 검색 경로(hybrid / email / HippoRAG)를 자동 선택 |
| `list_datasets` / `get_dataset` | dataset 목록·상세 (`use_when` 노트 포함) |
| `upload` | 파일/폴더 자동 판별 ingest. 기본 `async=true` |
| `list_documents` / `get_document_content` | 문서 브라우징 · 원문 조회 |
| `get_job` | `upload` async 응답의 `job_id` 폴링 (공개라 한 round-trip에 닫힘) |
| `admin_help` | 숨겨진 관리 도구 카탈로그 게이트웨이 |

`admin_help`로 노출되는 도구군: **파괴적**(`create_dataset`, `delete_dataset`, `delete_document`) · **진단**(`health`, `get_document`, `list_chunks`) · **그래프**(`graph_query`, `graph_rebuild`) · **HippoRAG**(`hipporag_index`, `hipporag_search`, `hipporag_stats`, …) · **파이프라인**(`list_pipelines`, `save_pipeline`, `open_pipeline_editor`, …).

## 동작 흐름

```
upload(path, [pipeline])  →  ingest 파이프라인 → SQLite/Qdrant/그래프 투영
   ├ 동기:  결과 즉시 반환
   └ async: { job_id, next_step: "Call get_job(...)" }  →  get_job 폴링

search(query, dataset_ids?)
   └ dataset metadata.preferred_search_pipeline에 따라
       default(hybrid) · email · hipporag 경로 자동 선택
```

`tools/list`의 `dataset_id` / `dataset_ids` 파라미터에는 **현재 등록된 dataset과 각 `use_when` 노트**가 동적으로 들어갑니다. 에이전트는 파이프라인이 아닌 dataset만 고르면 됩니다.

## 설치

```powershell
.\claude-mcp-add-retriever.ps1
```

Claude Code CLI에 등록합니다. 의존성은 첫 도구 호출 시 백그라운드 `pip install`로 자동 설치(`boot_doctor`).

`.env.example` → `.env` 복사 후 편집:

```env
RETRIEVER_DATA_ROOT=                       # 비우면 platform-default
RETRIEVER_DEFAULT_DATASETS=my_docs
EMBEDDING_API_URL=https://api.openai.com/v1/embeddings
EMBEDDING_API_KEY=sk-...
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIM=1536
```

`EMBEDDING_API_URL`을 비우면 FTS5 키워드 전용. HippoRAG는 `EMBEDDING_*` + `LLM_*` 필요(LLM 값 비면 EMBEDDING 값 자동 재사용).

> `load_dotenv(override=True)`: `.env`가 OS 환경변수를 항상 이깁니다(만료 키 silent 우선 사고 방지).

## 한국어 검색

색인·쿼리 양쪽 `kiwipiepy` 형태소. **2글자 한국어**("메일", "엔진")도 매치. 합성어("회의록")는 한 형태소라 "회의"로는 안 잡힘. 스키마 버전 변경 시 자동 재색인.

## 파이프라인 프로파일

| profile | 용도 |
|---|---|
| `default` | 하이브리드(FTS5 + Qdrant, linear fusion, parent-replace) |
| `keyword_only` | FTS5 + RRF만, 임베딩 API 우회 |
| `email` | `.pst` / 변환된 이메일 디렉토리 |
| `rrf_rerank` | RRF + BGE cross-encoder rerank |
| `rrf_llm_rerank` | RRF + LLM rerank |
| `rrf_graph_rerank` | RRF + 그래프 이웃 + BGE rerank |

토폴로지는 모두 node-centric JSON(`retriever/pipelines/<name>_unified.json`). `open_pipeline_editor`로 비주얼 편집 가능.

## 그래프 / HippoRAG

임베디드 Kùzu(`GraphDB/`)에 Document/Chunk/Dataset 노드 + IN_DATASET/HAS_CHUNK/NEXT/MENTIONS/SYNONYM 엣지를 투영합니다. SQLite가 source of truth, Kùzu는 derived.

- `graph_query`: 실행 전 자동 sync. `LIMIT` 미지정 시 안전 한도 부착. 파괴적 키워드(CREATE/DELETE/MERGE/SET/DROP/ALTER/REMOVE) 거부.
- `graph_rebuild`: Kùzu **COPY FROM 벌크 로더** — 청크 1만+엔티티 5천 규모도 수 초.
- HippoRAG: `upload(..., auto_hipporag=true)` → LLM OpenIE → entities/triples/mentions. 검색 시 쿼리 엔티티 → seed → scipy.sparse PPR(`data_root/ppr_matrix.npz` 캐시) → 청크 랭킹.

## 테스트

```powershell
py -3.12 scripts_test\e2e_stdio.py                     # MCP stdio 풀 round-trip
py -3.12 scripts_test\test_json_pipeline.py            # JSON 토폴로지 정합성
py -3.12 -m unittest discover -s tests -p "test_*.py"  # 유닛
```

`e2e_stdio.py`는 임시 data_root에서 임베딩 없이 keyword-only로 전체 도구를 검증합니다.

## Claude 설정 예시

```json
{
  "mcpServers": {
    "retriever": {
      "command": "py",
      "args": ["-3.12", "C:\\Users\\<YOU>\\slsi-cowork-plugins\\hybrid-retriever-modular-mcp\\server.py"]
    }
  }
}
```

## 제한

- PDF/Office 파싱: `pypdf`, `python-docx`, `openpyxl`. 암호화/스캔 PDF는 OCR 필요.
- 임베딩 API: OpenAI-호환 응답(`data: [{embedding, index}]`).
- Qdrant: 임베디드 모드만, 한 프로세스 단독 접근(path-lock).
