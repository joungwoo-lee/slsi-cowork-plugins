# email-mcp

`email-connector` 스킬을 **stdio MCP 서버**로 감싼 패키지. Claude Desktop / Claude Code가 사용자 PC의 PST 인덱스에 직접 검색·읽기·진단·인덱싱 호출을 할 수 있게 한다.

## 노출하는 MCP 도구 (10개)

### 검색 / 읽기
| 이름 | 용도 | 핵심 인자 |
|---|---|---|
| `search` | 하이브리드 검색 (FTS5 + Qdrant) | `query`, `mode` (`hybrid`/`keyword`/`semantic`), `top` |
| `list_mails` | 최신순 메일 목록 (sender/subject substring 필터, 페이지네이션) | `sender_like`, `subject_like`, `limit`, `offset` |
| `read_mail` | 메일의 통합 마크다운(`body.md`) 본문 | `mail_id` |
| `read_meta` | 메일 헤더(`meta.json`) — body.md 보다 가벼움 | `mail_id` |
| `read_attachment` | 첨부 목록 또는 단일 첨부 파일 메타(절대경로/크기/MIME) | `mail_id`, `filename` (생략 시 목록) |
| `stats` | 인덱스 카운트 + 경로 (sqlite total/with_vector, files_root_dirs) | — |

### 파이프라인 (쓰기)
| 이름 | 용도 | 핵심 인자 |
|---|---|---|
| `convert` | Phase 1만: PST → `body.md` + `meta.json` + 원본 첨부 | `limit` (필수), `pst` |
| `index` | Phase 2만: `Files/` → SQLite FTS5 (+ Qdrant) | `skip_embedding`, `mail_ids` |
| `ingest` | Phase 1 + 2 래퍼 | `limit` (필수), `skip_embedding`, `skip_convert`, `skip_index`, `pst` |

### 진단
| 이름 | 용도 | 핵심 인자 |
|---|---|---|
| `doctor` | Python/deps/.env/PST_PATH/임베딩 API 도달성 검사 | `skip_api`, `skip_pst` |

> `convert` / `index` / `ingest` 는 PST 전체를 돌리면 분~시간 단위라 MCP 클라이언트가 타임아웃됨. **`limit`이 필수**이며, 풀 인덱싱은 `email-connector` CLI(`py -3.9 scripts\ingest.py`)로 돌리고 MCP는 추가 배치/검수 용으로 사용한다. `index`는 `mail_ids`로 일부만 재인덱싱 가능.

## 동작 구조

이 MCP 서버는 **`email-connector`와 같은 Python 3.9 인터프리터** 위에서 `email-connector/scripts/*`를 직접 import 한다. 별도 프로세스나 SDK 의존성이 없다 (MCP Python SDK는 Python 3.10+ 요구, 그러나 `libpff-python`은 cp39-win_amd64 wheel만 존재 → 같은 3.9에서 동작해야 한다). MCP JSON-RPC 2.0 / stdio 프로토콜은 표준 라이브러리만으로 직접 구현했다.

```
Claude Desktop / Code  ──stdio──>  py -3.9 server.py  ──in-process──>  email-connector/scripts/{search,doctor,convert,index,storage}
                                                                              └──> SQLite FTS5 + Qdrant + 임베딩 API
```

## 패키지 구조

```
email-mcp/
├── server.py                       # 진입점 (얇음 — 3.9 가드 + main 호출만)
├── README.md / SETUP.md
├── requirements.txt
├── claude_desktop_config.example.json
└── mcp_server/                     # MCP 서버 본체 (한 통짜 X)
    ├── __init__.py                 # bootstrap 트리거 + main export
    ├── bootstrap.py                # 부팅: stdout 셋업 + email-connector 경로 발견
    ├── protocol.py                 # JSON-RPC 2.0 framing helpers
    ├── runtime.py                  # silenced_stdout, env path resolver, log
    ├── catalog.py                  # 10개 도구의 inputSchema 카탈로그 (data only)
    ├── handlers.py                 # 10개 tool 구현 (email-connector library 호출)
    └── dispatch.py                 # initialize / tools/list / tools/call 라우터 + 메인 루프
```

각 모듈의 책임은 `mcp_server/__init__.py` 상단의 docstring에 정리.

## 사전 조건

1. **email-connector가 먼저 셋업되어 있어야 한다.** `slsi-cowork-plugins/email-connector/SETUP.md`를 따라 Python 3.9 + 의존성 + `.env` + PST 인덱싱까지 끝낸 상태가 전제. `doctor` MCP 도구로 검증 가능.
2. Windows 10/11 네이티브.
3. `email-mcp/` 와 `email-connector/` 가 같은 부모 폴더에 있거나, 환경변수 `EMAIL_CONNECTOR_PATH` 로 경로가 지정돼 있어야 한다.

## 빠른 설치

```cmd
:: 1. email-connector 셋업 끝나 있다고 가정 (없으면 그쪽 SETUP.md부터)
:: 2. 이 폴더를 email-connector와 같은 부모 아래에 둔다
::    %USERPROFILE%\.claude\skills\email-mcp\
::    %USERPROFILE%\.claude\skills\email-connector\

:: 3. 추가 의존성 없음 (서버는 표준 라이브러리만 사용; email-connector deps 그대로 재사용)

:: 4. 동작 확인 (서버 단독 기동 + initialize 한 번 보내기 — 자세한 절차는 SETUP.md STEP 2)
echo {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"manual","version":"0"}}} | py -3.9 server.py
```

## Claude Desktop 연결

`%APPDATA%\Claude\claude_desktop_config.json` 의 `mcpServers` 에 추가:

```json
{
  "mcpServers": {
    "email": {
      "command": "py",
      "args": [
        "-3.9",
        "C:\\Users\\<YOU>\\.claude\\skills\\email-mcp\\server.py"
      ],
      "env": {
        "EMAIL_CONNECTOR_PATH": "C:\\Users\\<YOU>\\.claude\\skills\\email-connector"
      }
    }
  }
}
```

`claude_desktop_config.example.json` 에 그대로 복붙 가능한 예시 있음. Claude Desktop 재시작 후 도구 10개가 노출된다.

## Claude Code 연결

```cmd
claude mcp add email py -3.9 %USERPROFILE%\.claude\skills\email-mcp\server.py ^
  --env EMAIL_CONNECTOR_PATH=%USERPROFILE%\.claude\skills\email-connector
```

## 환경변수

| 이름 | 기본값 | 의미 |
|---|---|---|
| `EMAIL_CONNECTOR_PATH` | sibling 폴더 자동 탐지 | email-connector 스킬 폴더 절대경로 |
| `EMAIL_MCP_ENV` | `<EC>/​.env` | 사용할 .env 파일 경로 (스킬과 다른 .env를 쓰고 싶을 때) |

## 트러블슈팅

| 증상 | 원인/대응 |
|---|---|
| Claude가 도구 목록을 못 받음 | `py -3.9 server.py` 직접 실행해서 stderr에 어떤 에러가 뜨는지 확인. `email-connector` 경로 문제면 `EMAIL_CONNECTOR_PATH` 명시. |
| `doctor` 결과 `dep:libpff-python` ok=false | email-connector 셋업 미완. 그쪽 SETUP.md STEP 5 진행. |
| `search` 응답이 비어 있음 | PST가 아직 인덱싱되지 않음. `stats` 도구로 `sqlite.total_mails` 확인. 0이면 CLI에서 `py -3.9 scripts\ingest.py` 또는 MCP `ingest` 도구로 인덱싱. |
| `read_attachment` 가 path만 반환 | 의도된 설계. MCP 클라이언트는 같은 PC에 있으므로 절대경로로 직접 열 수 있다. base64 인라인 반환은 큰 파일에서 컨텍스트 폭발 위험. |
| stdout에 JSON 외 문자 섞여서 클라가 끊김 | `runtime.silenced_stdout()` 로 stdout 가드 중. server.py / mcp_server 안에서 직접 print 추가하지 말 것 — 모든 디버그는 `runtime.log()` (stderr). |

자세한 protocol 동작은 `mcp_server/protocol.py` / `mcp_server/dispatch.py` 코드 주석 참조.
