# hybrid-retriever-modular-mcp

자체 완결형 로컬 RAG MCP 서버. `py server.py`가 stdio MCP 서버를 띄우고, 도구 호출 시 로컬 SQLite FTS5 (kiwipiepy 한국어 형태소) + 선택적 Qdrant 벡터 + 임베디드 Kùzu 그래프를 in-process로 사용합니다. FastAPI 백엔드가 따로 필요하지 않습니다.

파이프라인 편집 UI는 MCP tool로 띄웁니다. 에이전트가 `open_pipeline_editor`를 호출하면 브라우저를 열고, 좌측에서 단계별 모듈 추가/설정/연결을 편집하고 우측에서 DAG 그래프를 바로 확인할 수 있습니다.

## 구조

```
Claude / 다른 MCP 클라이언트
       │  (stdio JSON-RPC)
       ▼
 py server.py
       │
       └── mcp_server/   ─ JSON-RPC 디스패치, 도구 카탈로그/핸들러
              │
              └── retriever/
                     ├── config.py       — .env + 프로세스 env 병합 (override=True)
                     ├── storage.py      — SQLite FTS5 + Qdrant primitives
                     ├── graph.py        — 임베디드 Kùzu (Cypher)
                     ├── morph.py        — 한국어 형태소 토큰화
                     ├── embedding_client.py — HTTP 임베딩 API
                     ├── components/     — Haystack @component 블록
                     ├── pipelines/      — JSON 토폴로지 + 프로파일 레지스트리
                     ├── stores/         — Haystack DocumentStore (SQLite FTS5)
                     └── api.py          — 핸들러에서 호출하는 facade
```

## 도구 (MCP tools)

| 도구 | 설명 |
|---|---|
| `search` | dataset metadata를 보고 자동으로 검색 경로를 선택해 chunk를 검색. 일반 hybrid / email / HippoRAG 경로를 서버가 내부적으로 결정 |
| `list_datasets`, `get_dataset` | 데이터셋 목록/상세 조회. `use_when`과 dataset metadata 확인 |
| `upload` | 파일/폴더 경로를 자동 판별해 ingest. 기본 `async=true`; 오래 걸리는 작업은 `job_id`와 다음 단계 안내를 반환 |
| `list_documents` | dataset 안의 문서 목록 브라우징 |
| `get_document_content` | 저장된 원문 텍스트 조회 (data_root 외부 경로 차단) |
| `admin_help` | 기본 `tools/list`에서 숨겨진 관리용 도구와 사용 시점 안내 |

기본 `tools/list`에는 검색/업로드/브라우징에 필요한 최소 도구만 노출합니다. 그 외 관리/진단/고급 그래프 도구는 `admin_help`에서 확인합니다. 예: `create_dataset`, `delete_dataset`, `get_job`, `get_document`, `list_chunks`, `delete_document`, `health`, `graph_query`, `graph_rebuild`, `hipporag_index`, `hipporag_refresh_synonyms`, `list_pipelines`, `save_pipeline`, pipeline editor 관련 도구 등.

## Dataset Metadata 중심 설계

이 서버는 **파이프라인 설명을 직접 고르게 하는 방식** 대신, dataset metadata를 source of truth로 사용합니다.

첫 ingest 시 dataset metadata에 다음을 기록합니다.

- `use_when`: 이 dataset을 언제 검색해야 하는지
- `first_ingest_pipeline`, `last_ingest_pipeline`
- `content_kind`
- `has_vectors`
- `has_hipporag`
- `supported_search_pipelines`
- `preferred_search_pipeline`

이후 검색 시에는 `search(dataset_ids=...)`만 호출하면 서버가 dataset metadata를 보고 자동으로 검색 경로를 선택합니다.

- 일반 문서 dataset: 기본 hybrid search
- email dataset: email profile 기반 search
- HippoRAG 준비 완료 dataset: HippoRAG 경로

여러 dataset을 한 번에 검색하는데 선호 경로가 다르면 안전하게 `default` 경로로 내립니다.

`tools/list` 응답의 dataset 관련 파라미터(`dataset_id`, `dataset_ids`)에는 **현재 등록된 dataset 목록과 각 dataset의 `use_when`** 이 동적으로 노출됩니다. 즉 에이전트는 pipeline 설명이 아니라 dataset 설명을 보고 dataset을 고르면 됩니다.

## 장기 작업

`upload`는 기본적으로 `async=true`입니다. 오래 걸리는 작업은 즉시 background job으로 시작하고, 응답에 다음이 포함됩니다.

- `job_id`
- `status`
- `next_step`: `get_job(job_id=...)` 호출 안내

`get_job` 자체는 관리용 도구로 숨겨져 있으며, 필요할 때는 `upload` 응답이나 `admin_help`가 안내합니다.

## HippoRAG 지식 그래프 (선택)

**관계 기반 / 멀티홉 질문**에 강한 retrieval. SQLite를 source of truth로 쓰고 Kùzu에는 투영만 합니다.

```
upload(path=..., auto_hipporag=true)
   │  ├ 청크 → SQLite/Qdrant (기존 경로)
   │  └ LLM OpenIE → triples → entities → mentions → SQLite
   ▼
hipporag_refresh_synonyms        (배치 끝에 1회)
   │  └ 엔티티 임베딩 cosine all-pairs → SYNONYM 엣지
   ▼
search(dataset_ids=[...])        # dataset metadata가 hipporag 경로를 선택
   ├ 쿼리 LLM → 핵심 엔티티 추출
   ├ 임베딩 cosine linker → 시드 엔티티
   ├ scipy.sparse PPR (`data_root/ppr_matrix.npz` 디스크 캐시, 그래프 변경 시 자동 무효화)
   └ Σ PPR(e) · log(1+mention_count) → 청크 랭킹
```

전제: `EMBEDDING_API_*` 설정. `LLM_*`가 비어 있으면 OpenAI embedding 설정을 기반으로 LLM 호출도 자동 구성합니다.

- `LLM_API_KEY` 없으면 `EMBEDDING_API_KEY` 재사용
- `LLM_API_X_DEP_TICKET` 없으면 `EMBEDDING_API_X_DEP_TICKET` 재사용
- `LLM_API_X_SYSTEM_NAME` 없으면 `EMBEDDING_API_X_SYSTEM_NAME` 재사용
- `LLM_TIMEOUT_SEC`, `LLM_VERIFY_SSL`도 없으면 `EMBEDDING_*` 값 사용
- OpenAI 임베딩 엔드포인트를 쓰는 경우 기본 LLM URL은 `/v1/chat/completions`, 기본 모델은 `gpt-4o-mini`

`graph_rebuild`는 이제 **Kùzu COPY FROM 벌크 로더**로 동작 — 청크 1만 + 엔티티 5천 규모도 수 초 안에 재구축. 기존의 청크 1개당 3 Cypher round-trip 방식과 비교하면 약 1-2 orders of magnitude 빠름.

## 설치

```powershell
.\claude-mcp-add-retriever.ps1
```

Claude Code CLI에 MCP를 등록합니다. **의존성은 첫 도구 호출 시 자동 설치** — `mcp_server/dispatch.boot_doctor`가 누락 패키지를 감지하고 백그라운드로 `pip install -r requirements.txt`를 실행합니다.

`.env.example`을 `.env`로 복사한 뒤 실제 값으로 편집:

```env
RETRIEVER_DATA_ROOT=                       # 비우면 platform-default 사용
RETRIEVER_DEFAULT_DATASETS=my_docs
EMBEDDING_API_URL=https://api.openai.com/v1/embeddings
EMBEDDING_API_KEY=sk-...
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIM=1536
```

`EMBEDDING_API_URL`을 비우면 SQLite FTS5 키워드 검색만 동작합니다 (정상). semantic search가 필요하면 4줄을 채우세요.

> ⚠ `load_dotenv(override=True)`: `.env`의 값이 항상 OS 환경변수를 이깁니다. 옛 셸에 남아있는 만료된 키가 silent하게 우선되는 사고를 막기 위함입니다.

## 한국어 검색

FTS5는 `unicode61` 토크나이저를 쓰지만, 색인·쿼리 양쪽에서 `kiwipiepy` 형태소 분석을 거칩니다. "메일" / "엔진" 같은 **2글자 한국어**도 매치됩니다. 합성어 (예: "회의록")는 한 형태소로 취급되므로 "회의"로는 잡히지 않습니다. 인덱스 스키마 버전이 올라가면 (`PRAGMA user_version`) 첫 실행 시 자동 재색인됩니다.

## 그래프

임베디드 Kùzu (`GraphDB/` 디렉토리, Docker 불필요)로 Document/Chunk/Dataset 노드 + IN_DATASET/HAS_CHUNK/NEXT 엣지를 저장합니다.

- `graph_query`는 실행 전에 자동 sync를 시도합니다
- 신규 row는 incremental sync
- 삭제/재업로드가 섞인 경우는 dirty 표시 후 안전하게 full rebuild
- `LIMIT` 미지정 시 안전 한도가 자동 부착되며 destructive 키워드(CREATE/DELETE/MERGE/SET/DROP/ALTER/REMOVE)는 거부됩니다.

## 파이프라인 프로파일

기본 프로파일은 `retriever/pipelines/registry.json`에 있습니다. 파이프라인 폴더의 토폴로지 JSON은 모두 node-centric 형식으로 저장되고, 실행 시점에만 Haystack 형식으로 어댑터 변환됩니다.

중요한 변경:

- `search`는 더 이상 `pipeline` 파라미터를 노출하지 않습니다
- `upload`만 `pipeline` 파라미터를 가집니다
- 즉 **파이프라인 선택은 ingest 단계에서만 사용자에게 보이고**, 검색 단계에서는 dataset metadata 기반 자동 라우팅을 사용합니다

`list_pipelines`, `save_pipeline`, pipeline editor 관련 도구는 관리용이므로 기본 `tools/list`에서는 숨기고 `admin_help`로 안내합니다.

### 비주얼 파이프라인 편집기

MCP tool 호출:

- `open_pipeline_editor`: 백그라운드로 UI 서버 실행, 이미 실행 중이면 재사용, URL 반환
- `get_pipeline_editor`: 현재 실행 여부 / URL / PID 확인
- `close_pipeline_editor`: 실행 중인 UI 종료

에디터 특징:

- 좌측: 단계별 모듈 카탈로그, 모듈별 init parameter 편집, connection 편집
- 우측: 현재 indexing/retrieval 파이프라인의 연결 그래프(SVG DAG)
- 저장 결과:
  - `retriever/pipelines/<name>_indexing.json`
  - `retriever/pipelines/<name>_retrieval.json`
  - `$RETRIEVER_DATA_ROOT/pipelines.json`

에디터도 저장 파일을 그대로 node-centric으로 읽어 시각화합니다.

| profile | 용도 |
|---|---|
| `default` | 하이브리드 (FTS5 + Qdrant, linear fusion, parent-replace) |
| `keyword_only` | FTS5 + RRF만, 임베딩 API 완전 우회 |
| `email` | `.pst` / 변환된 이메일 디렉토리 인덱싱 |
| `rrf_rerank` | RRF + BGE cross-encoder rerank |
| `rrf_llm_rerank` | RRF + LLM rerank |
| `rrf_graph_rerank` | RRF + 그래프 이웃 분기 + BGE rerank |

각 파이프라인의 자세한 "use when" 설명은 대응되는 `retriever/pipelines/<name>_unified.json`의 `metadata.description`에서 직접 확인하거나 `list_pipelines`로 조회하세요.

## 테스트

```powershell
py -3.12 scripts_test\e2e_stdio.py                     # MCP stdio 풀 round-trip
py -3.12 scripts_test\test_json_pipeline.py            # JSON 토폴로지 정합성
py -3.12 -m unittest discover -s tests -p "test_*.py"  # 유닛 테스트
```

`e2e_stdio.py`는 임시 데이터 루트에서 임베딩 없이 keyword-only 경로로 전체 도구를 검증합니다.

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

- PDF/Office 파싱은 `pypdf`, `python-docx`, `openpyxl`. 암호화/스캔 PDF는 OCR 필요.
- 임베딩 API는 OpenAI-호환 응답 형태 (`data: [{embedding: [...], index: int}]`).
- Qdrant는 임베디드 모드로만 운영하며 path-lock 충돌을 막기 위해 한 번에 한 프로세스에서만 접근하세요.
