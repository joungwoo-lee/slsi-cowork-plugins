# hybrid-retriever-modular-mcp

자체 완결형 로컬 RAG MCP 서버. `py server.py`가 stdio MCP 서버를 띄우고, 도구 호출 시 로컬 SQLite FTS5 (kiwipiepy 한국어 형태소) + 선택적 Qdrant 벡터 + 임베디드 Kùzu 그래프를 in-process로 사용합니다. FastAPI 백엔드가 따로 필요하지 않습니다.

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

기본 프로파일은 `retriever/pipelines/registry.json`. 사용자 프로파일은 `$RETRIEVER_DATA_ROOT/pipelines.json` 또는 `save_pipeline` MCP 도구로 추가합니다. 토폴로지(컴포넌트 그래프) 자체는 `default_indexing.json` / `default_retrieval.json` / `email_indexing.json`.

| profile | 용도 |
|---|---|
| `default` | 하이브리드 (FTS5 + Qdrant, linear fusion, parent-replace) |
| `keyword_only` | FTS5 + RRF만, 임베딩 API 완전 우회 |
| `email` | `.pst` / 변환된 이메일 디렉토리 인덱싱 |

## 테스트

```powershell
py -3 scripts_test\e2e_stdio.py                     # MCP stdio 풀 round-trip
py -3 scripts_test\test_json_pipeline.py            # JSON 토폴로지 정합성
py -3 -m unittest discover -s tests -p "test_*.py"  # 유닛 테스트
```

`e2e_stdio.py`는 임시 데이터 루트에서 임베딩 없이 keyword-only 경로로 전체 도구를 검증합니다.

## Claude 설정 예시

```json
{
  "mcpServers": {
    "retriever": {
      "command": "py",
      "args": ["-3", "C:\\Users\\<YOU>\\slsi-cowork-plugins\\hybrid-retriever-modular-mcp\\server.py"]
    }
  }
}
```

## 제한

- PDF/Office 파싱은 `pypdf`, `python-docx`, `openpyxl`. 암호화/스캔 PDF는 OCR 필요.
- 임베딩 API는 OpenAI-호환 응답 형태 (`data: [{embedding: [...], index: int}]`).
- Qdrant는 임베디드 모드로만 운영하며 path-lock 충돌을 막기 위해 한 번에 한 프로세스에서만 접근하세요.
