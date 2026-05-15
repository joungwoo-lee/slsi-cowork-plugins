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
| `search` | dataset의 chunk를 키워드/하이브리드 검색. `linear`/`rrf` fusion, metadata 필터, parent chunk replace 지원 |
| `list_datasets`, `get_dataset`, `create_dataset`, `delete_dataset` | 데이터셋 관리 |
| `upload_document`, `upload_directory` | 로컬 TXT/MD/PDF/DOCX/XLSX/CSV 파일을 복사·청킹·SQLite 색인·선택적 임베딩 |
| `list_documents`, `get_document`, `list_chunks`, `delete_document` | 문서·청크 관리 |
| `get_document_content` | 저장된 원문 텍스트 조회 (data_root 외부 경로 차단) |
| `list_pipelines`, `save_pipeline` | 등록된 파이프라인 프로파일 조회·저장 |
| `open_pipeline_editor`, `get_pipeline_editor`, `close_pipeline_editor` | 비주얼 파이프라인 편집기 실행/상태 조회/종료 |
| `health` | DB, 데이터 루트, 임베딩 설정, 인덱스 카운트 확인 |
| `graph_query`, `graph_rebuild` | Kùzu 그래프 위 Cypher 질의 (read-only) / 재빌드 |

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

임베디드 Kùzu (`GraphDB/` 디렉토리, Docker 불필요)로 Document/Chunk/Dataset 노드 + IN_DATASET/HAS_CHUNK/NEXT 엣지를 저장. `graph_rebuild` 후 `graph_query`로 Cypher 사용. `LIMIT` 미지정 시 안전 한도가 자동 부착되며 destructive 키워드(CREATE/DELETE/MERGE/SET/DROP/ALTER/REMOVE)는 거부됩니다.

## 파이프라인 프로파일

기본 프로파일은 `retriever/pipelines/registry.json`(컴포넌트 그래프 참조 + 오버라이드만 보관). 각 파이프라인의 "언제 사용해야 하는지" 설명은 **해당 토폴로지 JSON의 `metadata.description`** 에 들어 있어 — 사용자 프로파일은 `$RETRIEVER_DATA_ROOT/pipelines.json` 또는 `save_pipeline` MCP 도구로 추가합니다 (이 경우에도 description은 새로 생성되는 토폴로지 JSON의 metadata에 함께 기록됩니다). 파이프라인 폴더의 토폴로지 JSON은 모두 node-centric 형식으로 저장되고, 실행 시점에만 Haystack 형식으로 어댑터 변환됩니다.

`tools/list` 응답에서는 `search` / `upload_document` / `upload_directory`의 `pipeline` 파라미터 description에 현재 등록된 모든 프로파일의 description 목록이 합성되어 노출됩니다. 즉 에이전트가 별도로 `list_pipelines`를 호출하지 않아도 도구 스키마만 보고 "쿼리에 맞는 파이프라인"을 고를 수 있습니다.

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
