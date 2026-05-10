# email-mcp 셋업 가이드

`email-mcp`를 클라이언트 PC(Windows)에 설치하고 Claude Desktop / Code에 연결하는 절차서. 에이전트가 그대로 따라 실행할 수 있게 단계 마커(`[USER]` / `[AGENT]` / `[CHECK]`)를 사용한다.

> **TL;DR**: `install.cmd` 더블클릭. 막히면 메시지대로 따라가고, 그래도 안 되면 아래 STEP A 부터 수동으로.

## 자동 설치 (권장)

email-mcp 폴더의 `install.cmd` 를 더블클릭하거나 콘솔에서:
```cmd
cd /d %USERPROFILE%\.claude\skills\email-mcp
install.cmd
```

`install.ps1` 이 다음을 자동 처리:
1. Windows / Python 3.9 64-bit / `py` 런처 검증
2. email-connector 위치 확인 (`-EmailConnectorPath` 로 override 가능, 기본은 sibling)
3. 누락된 email-connector 의존성 `pip install`
4. `.env` 자동 생성 (없으면 `.env.example` 복사)
5. 서버 stdio 스모크 테스트 (initialize 한 번 보내고 `serverInfo.name == "email-mcp"` 확인)
6. `%APPDATA%\Claude\claude_desktop_config.json` 머지 — 기존 파일은 `.bak.<timestamp>` 로 백업, BOM 없는 UTF-8 로 저장, 다시 읽어 검증
7. `claude_code_install.cmd` 생성 (Claude Code CLI 사용자용)
8. `doctor.py --skip-api` 돌려 잔여 이슈 출력

옵션:
- `install.cmd -DryRun` — 아무것도 안 쓰고 검사만
- `install.cmd -SkipClaudeConfig` — Desktop 머지 생략
- `install.cmd -SkipDeps` — pip 생략

설치 후 **`<email-connector>\.env`** 만 실제 값으로 편집하고 Claude Desktop 재시작.

자동 설치가 어디서 막히면 그 메시지에 따라 아래 STEP 으로 들어와 수동 처리.

---

## 수동 설치 절차

## 단계 마커
- **[USER]** — 사용자가 직접 해야 함. 완료 응답을 받기 전엔 다음 STEP으로 진행 금지.
- **[AGENT]** — 에이전트가 명령을 실행하고 결과를 보고.
- **[CHECK]** — 검증. 실패 시 표시된 STEP으로 회귀.

## 일반 원칙
1. **email-connector 셋업이 선행**되어야 한다. `email-connector/SETUP.md`의 STEP A(진단)부터 통과한 상태가 출발점.
2. 모든 Python 호출은 `py -3.9` 명시 — `python` / `py` 단독은 다른 인터프리터를 잡을 수 있다.
3. WSL/macOS/Linux 감지 시 즉시 중단. 이 스킬은 Windows 네이티브 전용.

---

## STEP A. email-connector 선행 검증 [AGENT][CHECK]

email-mcp는 email-connector를 in-process import 하므로, 그쪽이 깨져 있으면 어느 도구도 동작하지 않는다.

```cmd
cd /d %USERPROFILE%\.claude\skills\email-connector
py -3.9 scripts\doctor.py
```

- `all_ok: true` → STEP 1로.
- `all_ok: false` → `email-connector/SETUP.md`의 STEP A 매핑 표대로 그쪽을 먼저 고친다. 여기서 더 진행 금지.

## STEP 1. email-mcp 폴더 배치 [USER + AGENT][CHECK]

email-mcp 폴더를 email-connector와 **같은 부모 폴더** 아래에 두면 sibling 자동 탐지로 동작한다 (별도 환경변수 불필요).

권장 배치:
```
%USERPROFILE%\.claude\skills\
├── email-connector\         (이미 있어야 함)
└── email-mcp\               (이번에 추가)
    ├── server.py            (얇은 진입점)
    ├── README.md
    ├── SETUP.md
    ├── requirements.txt
    ├── claude_desktop_config.example.json
    └── mcp_server\          (서버 본체)
        ├── __init__.py
        ├── bootstrap.py
        ├── protocol.py
        ├── runtime.py
        ├── catalog.py
        ├── handlers.py
        └── dispatch.py
```

### 1-1. 복사 [USER]
> 이 폴더를 다음 위치로 복사해 주세요:
> ```cmd
> git clone https://github.com/joungwoo-lee/slsi-cowork-plugins %TEMP%\slsi-plugins
> xcopy /E /I /Y %TEMP%\slsi-plugins\email-mcp %USERPROFILE%\.claude\skills\email-mcp
> ```

### 1-2. 검증 [AGENT][CHECK]
```cmd
dir "%USERPROFILE%\.claude\skills\email-mcp\server.py"
dir "%USERPROFILE%\.claude\skills\email-connector\scripts\search.py"
```
둘 다 보이지 않으면 STEP 1-1 재실행.

## STEP 2. 서버 단독 기동 테스트 [AGENT][CHECK]

JSON-RPC `initialize` 한 번을 보내 `serverInfo`가 돌아오는지 확인한다.

```cmd
cd /d %USERPROFILE%\.claude\skills\email-mcp
echo {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"manual","version":"0"}}} | py -3.9 server.py
```

기대 출력 (한 줄, stdout):
```json
{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-06-18","capabilities":{"tools":{"listChanged":false}},"serverInfo":{"name":"email-mcp","version":"0.1.0"}}}
```

stderr에는 `[email-mcp] starting ... (email-connector at ...)` 한 줄이 보일 수 있다 (정상).

**실패 시:**
- `email-mcp requires Python 3.9` → STEP 0 (Python 3.9 설치, email-connector SETUP.md STEP 2 참조).
- `cannot find email-connector at ...` → STEP 1 폴더 위치 확인 또는 `set EMAIL_CONNECTOR_PATH=...` 명시.
- `import scripts.config` 실패 → email-connector 의존성 미설치. STEP A로 회귀.

## STEP 3. Claude Desktop 연결 [USER + AGENT]

### 3-1. 설정 파일 위치 확인
```cmd
dir "%APPDATA%\Claude\claude_desktop_config.json"
```
- 파일이 있으면 그 안의 `mcpServers`에 항목을 추가.
- 없으면 다음 내용으로 새로 생성. `<YOU>`를 실제 Windows 사용자명으로 치환.

### 3-2. 설정 작성 [AGENT]
`claude_desktop_config.example.json`을 참고:
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

> JSON 안 백슬래시는 반드시 `\\`로 두 번. 한 번이면 파싱 에러.

### 3-3. Claude Desktop 재시작 [USER]
설정 파일 변경은 재시작 후에만 반영. Claude Desktop 종료 → 재실행.

### 3-4. 도구 노출 검증 [USER][CHECK]
Claude Desktop 입력창 옆 도구 아이콘에서 `email` 서버의 도구 10개가 보이면 성공:
- 검색/읽기: `search`, `list_mails`, `read_mail`, `read_meta`, `read_attachment`, `stats`
- 파이프라인: `convert`, `index`, `ingest`
- 진단: `doctor`

도구가 안 보이면:
- Claude Desktop 로그 확인 (`%APPDATA%\Claude\logs\mcp-server-email.log`).
- STEP 2 단독 기동 테스트 다시 돌려 stderr 확인.

## STEP 4. Claude Code 연결 (선택) [AGENT]

Claude Desktop 대신 Claude Code CLI를 쓴다면:
```cmd
claude mcp add email py -3.9 %USERPROFILE%\.claude\skills\email-mcp\server.py ^
  --env EMAIL_CONNECTOR_PATH=%USERPROFILE%\.claude\skills\email-connector
claude mcp list
```
`email` 서버가 `connected` 상태로 보이면 성공.

## STEP 5. 도구 스모크 테스트 [AGENT][CHECK]

Claude Desktop / Code에서 다음 prompt를 보내 동작 확인:

1. **doctor**: "email-mcp의 doctor 도구로 진단해줘"
   → JSON `{"all_ok": true, "checks": [...]}` 반환되면 성공.
2. **stats**: "이메일 인덱스 stats 보여줘"
   → `{sqlite: {total_mails, with_vector}, files_root_dirs, ...}`. `total_mails` > 0 이어야 검색 가능.
3. **list_mails**: "이메일 목록 5개만 보여줘 (limit=5)"
   → `mails` 배열에 최신순 5개 반환.
4. **search** (PST 인덱싱이 끝난 상태에서): "email 검색으로 '회의' 관련 메일 5개 찾아줘"
   → 메일 메타 배열 반환.
5. **read_mail**: 위 결과의 mail_id 하나로 본문 읽기 요청.
   → `body.md` 내용이 그대로 표시.
6. **read_attachment**: 같은 mail_id로 첨부 목록 요청 (filename 생략).
   → `attachments` 배열에 파일명/크기.

`total_mails == 0` 이면 인덱싱이 안 된 상태 — `email-connector` CLI 로 `py -3.9 scripts\ingest.py` 돌리거나, MCP `ingest {limit: 50}` 으로 일부만 부어 보고 다시 stats 확인.

## 셋업 종료 보고
- ✅/❌ 각 STEP 결과
- Claude Desktop / Code 어느 쪽에 연결했는지
- 다음 사용 예시:
  > "이메일에서 협력사 보안 점검 보고서 찾아줘" → email-mcp.search 자동 호출
