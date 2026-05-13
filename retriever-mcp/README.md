# retriever-mcp

`hybrid_retriever_windows_local`(RAGFlow 호환 FastAPI 서버) 위에 얹는 **stdio MCP 서버**. Claude Desktop / Claude Code 가 사용자 PC 에서 돌고 있는 retriever_engine 의 검색·업로드·관리 API 를 도구로 직접 호출할 수 있게 한다.

`email-mcp` 와 같은 모듈 레이아웃을 따르지만, in-process import 가 아니라 **순수 HTTP 클라이언트**다. 그래서 의존성 0개(표준 라이브러리만), Python 버전 제약 없음.

## 노출하는 MCP 도구 (13개)

### 검색
| 이름 | 용도 | 핵심 인자 |
|---|---|---|
| `search` | `/api/v1/retrieval` 하이브리드 검색 (FTS5 + Qdrant local) → contexts + citations 반환 | `query`, `dataset_ids`, `top_n`, `vector_similarity_weight`, `pipeline_name` |

### 데이터셋
| 이름 | 용도 | 핵심 인자 |
|---|---|---|
| `list_datasets` | API 키가 볼 수 있는 데이터셋 목록 | — |
| `get_dataset` | 단일 데이터셋 메타 조회 | `dataset_id` |
| `create_dataset` | 빈 데이터셋 생성 (대부분은 `upload_document` 가 자동 생성하므로 거의 안 씀) | `name`, `description` |
| `delete_dataset` | 데이터셋 + 문서 + 청크 + 벡터 + 원본 파일 전체 삭제 (복구 불가) | `dataset_id` |

### 문서
| 이름 | 용도 | 핵심 인자 |
|---|---|---|
| `upload_document` | 로컬 파일 한 개를 업로드 → 서버가 파싱/청킹/임베딩/색인까지 동기 처리 | `dataset_id`, `file_path`, `use_hierarchical`, `use_contextual`, `pipeline_name` |
| `list_documents` | 데이터셋 안 문서 목록 (최신순) | `dataset_id`, `keywords`, `offset`, `limit` |
| `get_document` | 문서 메타 (청크 카운트, 인제스트 설정 등) | `dataset_id`, `document_id` |
| `list_chunks` | 문서가 어떻게 청크로 쪼개졌는지 확인 | `dataset_id`, `document_id`, `keywords` |
| `get_document_content` | 로컬 파일 저장소의 **원본** 내용 조회 (search 결과 확장용) | `dataset_id`, `document_id` |
| `delete_document` | 문서 + 청크/벡터 삭제 | `dataset_id`, `document_id` |

### 파이프라인 / 진단
| 이름 | 용도 | 핵심 인자 |
|---|---|---|
| `list_pipelines` | 서버에 정의된 ingest/retrieval 파이프라인 목록 + 기본값 | — |
| `health` | `/health/deep` — FTS5 / Qdrant / 임베딩 모델 / 파일 저장소 점검 (`shallow=true` 면 `/health`) | `shallow` |

> `upload_document` 는 서버가 동기적으로 임베딩까지 돌리므로 큰 파일일수록 오래 걸린다. MCP 타임아웃은 기본 10분으로 별도 설정되어 있다 (`RETRIEVER_TIMEOUT_SEC` 와 별개).

## 동작 구조

```
Claude Desktop / Code  ──stdio──>  py server.py  ──HTTP──>  retriever_engine FastAPI
                                                            └──> SQLite FTS5 + Qdrant local + 로컬 파일 저장소
```

retriever-mcp 는 `urllib` 만 사용해 RAGFlow 호환 REST 엔드포인트를 호출한다. multipart 업로드도 표준 라이브러리로 인코딩 — `requests` 같은 외부 패키지가 필요 없다.

## 패키지 구조

```
retriever-mcp/
├── server.py                       # 진입점 (얇음 — main 호출만)
├── README.md
├── SETUP.md
├── requirements.txt                 # 비어 있음 (stdlib only)
├── claude_desktop_config.example.json
├── claude-mcp-add-retriever.bat
├── opencode.json
└── mcp_server/                     # MCP 서버 본체
    ├── __init__.py                 # bootstrap 트리거 + main export
    ├── bootstrap.py                # 부팅: stdout 셋업 + base URL / API key / 기본 dataset 해석
    ├── protocol.py                 # JSON-RPC 2.0 framing
    ├── runtime.py                  # silenced_stdout, urllib HTTP helper, RetrieverHttpError
    ├── catalog.py                  # 13개 도구의 inputSchema 카탈로그
    ├── handlers.py                 # 13개 tool 구현 (HTTP 호출)
    └── dispatch.py                 # initialize / tools/list / tools/call 라우터 + 메인 루프
```

## 사전 조건

1. **`hybrid_retriever_windows_local` 의 retriever_engine 이 먼저 떠 있어야 한다.** 기본 `http://127.0.0.1:9380`. `health` 도구로 검증 가능.
2. Python 3.10+ (Windows / macOS / Linux 모두 OK — retriever-mcp 자체는 OS 의존성 없음). 단, 서버측 retriever_engine 은 Windows 네이티브 기준.
3. API 키는 retriever_engine 의 `REQUIRE_API_KEY` 설정과 일치해야 한다.

## 빠른 설치 (Windows, Claude Desktop)

email-mcp 와 같은 부모 폴더(예: `%USERPROFILE%\.claude\skills\`) 아래에 retriever-mcp 를 두고 `%APPDATA%\Claude\claude_desktop_config.json` 에 다음을 머지:

```json
{
  "mcpServers": {
    "retriever": {
      "command": "py",
      "args": [
        "-3",
        "C:\\Users\\<YOU>\\.claude\\skills\\retriever-mcp\\server.py"
      ],
      "env": {
        "RETRIEVER_BASE_URL": "http://127.0.0.1:9380",
        "RETRIEVER_API_KEY": "ragflow-key",
        "RETRIEVER_DEFAULT_DATASETS": "my_docs"
      }
    }
  }
}
```

Claude Desktop 재시작 후 13개 도구가 노출된다.

## Claude Code 연결

```cmd
claude mcp add retriever py -3 %USERPROFILE%\.claude\skills\retriever-mcp\server.py ^
  --env RETRIEVER_BASE_URL=http://127.0.0.1:9380 ^
  --env RETRIEVER_API_KEY=ragflow-key ^
  --env RETRIEVER_DEFAULT_DATASETS=my_docs
```

또는 `claude-mcp-add-retriever.bat` 더블클릭.

## 환경변수

| 이름 | 기본값 | 의미 |
|---|---|---|
| `RETRIEVER_BASE_URL` | `http://127.0.0.1:9380` | retriever_engine FastAPI 의 base URL |
| `RETRIEVER_API_KEY` | `ragflow-key` | Authorization Bearer 토큰 |
| `RETRIEVER_DEFAULT_DATASETS` | (빈 값) | `search` 등에서 `dataset_ids` 인자 생략 시 쓰는 기본 데이터셋 (콤마 구분) |
| `RETRIEVER_TIMEOUT_SEC` | `60` | 일반 HTTP 호출 타임아웃 (초). `upload_document` 만 자동으로 ≥600 초로 확장됨 |
| `RETRIEVER_VERIFY_SSL` | `true` | HTTPS 사용 시 인증서 검증 여부 — 현재 구현은 stdlib `urllib` 이라 시스템 trust store 를 그대로 따름 |

## 트러블슈팅

| 증상 | 원인/대응 |
|---|---|
| `connection failed for http://127.0.0.1:9380/...` | retriever_engine 이 안 떠 있다. `hybrid_retriever_windows_local/retriever_engine/scripts/start_windows.ps1` 실행. |
| `HTTP 401 from ...` | `RETRIEVER_API_KEY` 가 서버 `.env` 의 `API_KEY` 와 다르다. |
| `HTTP 403 ... Access denied to dataset 'X'` | API 키가 해당 dataset 접근 권한 없음. `list_datasets` 로 어떤 게 보이는지 확인. |
| `search` 가 빈 결과 | dataset 에 문서가 안 들어 있음. `list_documents` 로 확인 후 `upload_document` 로 채우기. `health` 로 임베딩 API 도 점검. |
| stdout 에 JSON 외 문자 섞여서 클라가 끊김 | `runtime.silenced_stdout()` 가드 안에서 도구가 실행된다. `server.py` / `mcp_server` 안에서 직접 `print` 추가 금지 — 모든 디버그는 `runtime.log()` (stderr). |

자세한 protocol 동작은 `mcp_server/protocol.py` / `mcp_server/dispatch.py` 코드 주석 참조.
