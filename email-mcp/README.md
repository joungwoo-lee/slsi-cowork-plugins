# email-mcp

`email-connector` 스킬을 **stdio MCP 서버**로 감싼 패키지. Claude Desktop / Claude Code (또는 다른 MCP 클라이언트)가 사용자 PC의 PST 인덱스에 직접 검색·읽기·진단·인덱싱 호출을 할 수 있게 해 준다.

## 노출하는 MCP 도구

| 이름 | 용도 | 주요 인자 |
|---|---|---|
| `search` | 하이브리드 검색 (FTS5 + Qdrant) | `query`, `mode` (`hybrid`/`keyword`/`semantic`), `top` |
| `read_mail` | 메일 ID로 통합 마크다운(`body.md`) 읽기 | `mail_id` |
| `doctor` | 설치/설정 진단 (Python/deps/.env/임베딩 API) | `skip_api`, `skip_pst` |
| `ingest` | 일부(`limit`개) 메일을 변환 + 인덱싱 | `limit` (필수), `skip_embedding`, `skip_convert`, `skip_index`, `pst` |

> `ingest`는 PST 전체를 돌리면 분~시간 단위라 MCP 클라이언트가 타임아웃됨. 풀 인덱싱은 CLI(`py -3.9 scripts\ingest.py`)로 돌리고, MCP에서는 추가 배치/검수 용으로만 사용.

## 동작 구조

이 MCP 서버는 **`email-connector`와 같은 Python 3.9 인터프리터** 위에서 `email-connector/scripts/*`를 직접 import 한다. 별도 프로세스나 SDK 의존성이 없다 (MCP Python SDK는 Python 3.10+ 요구, 그러나 `libpff-python`은 cp39-win_amd64 wheel만 존재 → 같은 3.9에서 동작해야 한다). MCP JSON-RPC 2.0 / stdio 프로토콜은 표준 라이브러리만으로 직접 구현했다.

```
Claude Desktop / Code  ──stdio──>  py -3.9 server.py  ──in-process──>  email-connector/scripts/{search,doctor,convert,index}
                                                                              └──> SQLite FTS5 + Qdrant + 임베딩 API
```

## 사전 조건

1. **email-connector가 먼저 셋업되어 있어야 한다.**
   `slsi-cowork-plugins/email-connector/SETUP.md`를 따라 Python 3.9 + 의존성 + `.env` + PST 인덱싱까지 끝낸 상태가 전제다. `doctor` MCP 도구로 검증할 수 있다.
2. Windows 10/11 네이티브.
3. `email-mcp/`와 `email-connector/`가 같은 부모 폴더에 있거나, 환경변수 `EMAIL_CONNECTOR_PATH`로 경로가 지정돼 있어야 한다.

## 설치

```cmd
:: 1. email-connector 셋업이 끝나 있다고 가정 (없으면 거기 SETUP.md부터)
:: 2. 이 폴더를 email-connector와 같은 부모 아래에 둔다
::    예: %USERPROFILE%\.claude\skills\email-mcp\
::        %USERPROFILE%\.claude\skills\email-connector\

:: 3. 추가 의존성 없음 (서버는 표준 라이브러리만 사용; email-connector의 의존성을 그대로 재사용)

:: 4. 동작 확인 (서버를 직접 띄워 initialize 한 번 보내보기)
py -3.9 server.py
```

서버는 stdin에서 JSON-RPC 한 줄을 기다린다. 종료는 Ctrl+Z (CMD) → Enter, 또는 stdin 닫기.

## Claude Desktop 연결

`%APPDATA%\Claude\claude_desktop_config.json`에 다음을 추가 (기존 `mcpServers`에 합쳐 넣기):

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

`claude_desktop_config.example.json`에 그대로 복붙 가능한 예시가 있다. Claude Desktop을 재시작하면 도구 목록에 `search` / `read_mail` / `doctor` / `ingest`가 노출된다.

## Claude Code 연결

```cmd
claude mcp add email py -3.9 C:\Users\<YOU>\.claude\skills\email-mcp\server.py ^
  --env EMAIL_CONNECTOR_PATH=C:\Users\<YOU>\.claude\skills\email-connector
```

또는 `~/.claude.json`의 `mcpServers`에 직접 추가.

## 환경변수

| 이름 | 기본값 | 의미 |
|---|---|---|
| `EMAIL_CONNECTOR_PATH` | sibling 폴더 자동 탐지 | email-connector 스킬 폴더 절대경로 |
| `EMAIL_MCP_ENV` | `<EC>/​.env` | 사용할 .env 파일 경로 (스킬과 다른 .env를 쓰고 싶을 때) |

## 트러블슈팅

| 증상 | 원인/대응 |
|---|---|
| Claude가 도구 목록을 못 받음 | `py -3.9 server.py` 직접 실행해서 stderr에 어떤 에러가 뜨는지 확인. `email-connector` 경로 문제면 EMAIL_CONNECTOR_PATH 명시. |
| `doctor` 결과 `dep:libpff-python` ok=false | email-connector 셋업 미완. 그쪽 SETUP.md STEP 5 진행. |
| `search` 응답이 비어 있음 | PST가 인덱싱되지 않음. CLI에서 `py -3.9 scripts\ingest.py` 또는 MCP `ingest` 도구로 인덱싱. |
| stdout에 JSON 외 문자 섞여서 클라가 끊김 | 서버는 stdout 쓰기를 가두고 있지만, 사용자가 server.py 안에서 print를 추가한 경우 등에서 발생 가능. 모든 디버그는 `print(..., file=sys.stderr)`. |
| `read_mail` not found | `body.md` 경로는 `<DATA_ROOT>\Files\<mail_id>\body.md`. 인덱싱 후에만 존재. |

자세한 protocol 동작은 `server.py` 코드 주석 참조.
