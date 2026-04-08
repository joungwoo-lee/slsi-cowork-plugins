# Excel Control Plugin

[mcp-server-excel](https://github.com/sbroenne/mcp-server-excel)을 stdio 방식으로 연동하여 Microsoft Excel을 AI 에이전트에서 직접 제어하는 플러그인입니다.

## 요구사항

- **Windows** (Excel COM 자동화)
- **Microsoft Excel 2016+**
- **PowerShell 5.1+** (Windows 기본 내장)
- 인터넷 연결 (GitHub 릴리즈 다운로드)

## 설치

PowerShell에서 실행:
```powershell
powershell -ExecutionPolicy Bypass -File "excel-control\skills\excel-control\scripts\setup_excel_mcp.ps1"
```

셋업 스크립트가 자동으로:
1. GitHub API에서 **최신 릴리즈**를 감지하고 다운로드
2. zip에서 `mcp-excel.exe` 위치를 자동 탐색하여 `%USERPROFILE%\ExcelMcp\`에 설치
3. Windows **PATH에 등록** → `mcp-excel` 명령으로 실행 가능
4. `.mcp.json`에 stdio MCP 서버 경로 설정
5. Claude Code / Claude Desktop / OpenCode / VS Code 설정 파일에 자동 등록
6. **stdio 핸드셰이크 테스트**로 실제 동작 검증

OpenCode는 `~/.config/opencode/opencode.json` 또는 `~/.config/opencode/opencode.jsonc`를 자동 갱신합니다.
기존 `jsonc` 파일에 주석이 있어도 주석을 제거한 뒤 안전하게 파싱하여 `excel-mcp` 서버를 추가합니다.

## 구조

```
excel-control/
├── .claude-plugin/
│   └── plugin.json                 # 플러그인 메타데이터
├── .mcp.json                       # MCP 서버 stdio 설정 (셋업 시 경로 자동 갱신)
├── skills/
│   └── excel-control/
│       ├── SKILL.md                # 스킬 정의 (25개 도구, 작업 규칙)
│       └── scripts/
│           └── setup_excel_mcp.ps1 # 원클릭 설치 스크립트 (PowerShell)
└── README.md
```

## 실행 흐름

### 1단계: 설치 (최초 1회)

```
사용자가 PowerShell에서 setup_excel_mcp.ps1 실행
    │
    ├─ GitHub API 호출 (/repos/sbroenne/mcp-server-excel/releases/latest)
    │   └─ 최신 버전 + zip 다운로드 URL 획득
    │
    ├─ ExcelMcp-MCP-Server-x.x.x-windows.zip 다운로드
    │   └─ zip 내부를 재귀 탐색하여 mcp-excel.exe 위치 확인
    │   └─ %USERPROFILE%\ExcelMcp\ 에 복사
    │
    ├─ Windows PATH 환경변수에 ExcelMcp 디렉토리 영구 등록
    │   └─ 이후 어디서든 "mcp-excel" 명령으로 실행 가능
    │
    ├─ 설정 파일 자동 갱신
    │   ├─ 플러그인 .mcp.json ← 풀패스로 command 기입
    │   ├─ ~/.claude/settings.json (Claude Code)
    │   ├─ %APPDATA%/Claude/claude_desktop_config.json (Claude Desktop)
    │   ├─ ~/.config/opencode/opencode.json 또는 opencode.jsonc (OpenCode)
    │   └─ .vscode/mcp.json (VS Code)
    │
    └─ stdio 핸드셰이크 테스트
        └─ mcp-excel.exe를 spawn → JSON-RPC initialize 전송 → 응답 확인
```

### 2단계: AI 에이전트 시작 시

```
AI 에이전트(Claude Code, OpenCode 등) 실행
    │
    └─ .mcp.json 로드
        {
          "mcpServers": {
            "excel-mcp": {
              "command": "C:\\Users\\이름\\ExcelMcp\\mcp-excel.exe"
            }
          }
        }
        │
        └─ mcp-excel.exe를 자식 프로세스로 spawn
            ├─ stdin  ← 에이전트가 JSON-RPC 요청 전송
            └─ stdout → 에이전트가 JSON-RPC 응답 수신
```

이 시점에서 에이전트는 25개 MCP 도구(Files, Ranges, Charts, PivotTables 등)를 사용할 수 있는 상태가 됩니다.

OpenCode에는 다음과 같은 형태로 등록됩니다:

```json
{
  "mcp": {
    "excel-mcp": {
      "type": "local",
      "command": ["C:\\Users\\이름\\ExcelMcp\\mcp-excel.exe"],
      "enabled": true
    }
  }
}
```

### 3단계: 사용자 프롬프트 → Excel 제어

```
사용자: "새 엑셀 파일 열고 A1에 '매출', B1에 '비용' 넣어줘"
    │
    ▼
AI 에이전트가 프롬프트 해석
    │
    ├─ [1] Files 도구 호출: 새 워크북 생성
    │   │  에이전트 → stdin → mcp-excel.exe
    │   │  {"jsonrpc":"2.0","method":"tools/call",
    │   │   "params":{"name":"files_operations",
    │   │            "arguments":{"operation":"create_workbook"}}}
    │   │
    │   │  mcp-excel.exe → COM → Excel.exe (실제 엑셀 프로세스 기동)
    │   │  mcp-excel.exe → stdout → 에이전트
    │   │  {"result":{"workbook":"Book1","path":"..."}}
    │   │
    ├─ [2] Ranges 도구 호출: A1에 '매출' 입력
    │   │  stdin → {"name":"range_write","arguments":{"range":"A1","value":"매출"}}
    │   │  stdout ← {"result":{"success":true}}
    │   │
    ├─ [3] Ranges 도구 호출: B1에 '비용' 입력
    │   │  stdin → {"name":"range_write","arguments":{"range":"B1","value":"비용"}}
    │   │  stdout ← {"result":{"success":true}}
    │   │
    ▼
사용자에게 "완료했습니다" 응답
```

### 엑셀 화면 표시

```
기본: Excel이 백그라운드에서 동작 (화면에 안 보임, 속도 빠름)
    │
사용자: "엑셀 창 띄워줘"
    │
    └─ Window Management 도구 호출
        └─ mcp-excel.exe → COM → Excel.Visible = true
            └─ 실제 Excel 창이 화면에 나타남 (작업 과정 실시간 확인 가능)
```

### 전체 아키텍처

```
┌─────────────────┐     stdio (JSON-RPC)     ┌──────────────┐     COM 자동화     ┌──────────────┐
│   AI 에이전트    │ ◄──────────────────────► │ mcp-excel.exe│ ◄───────────────► │ Excel.exe    │
│ (Claude Code,   │   stdin: 도구 호출 요청   │ (MCP Server) │   CreateWorkbook  │ (실제 엑셀)   │
│  OpenCode 등)   │   stdout: 실행 결과 반환  │              │   SetCellValue    │              │
└─────────────────┘                          └──────────────┘   CreateChart ...  └──────────────┘
        ▲                                                                              │
        │ 자연어 프롬프트                                                                │ 화면 표시
        │                                                                              ▼
┌─────────────────┐                                                          ┌──────────────┐
│     사용자       │                                                          │  엑셀 UI 창   │
└─────────────────┘                                                          └──────────────┘
```

## 사용 예시

AI 에이전트 프롬프트:

> "새로운 엑셀 파일을 열고, A1 셀에 '테스트', A2 셀에 '성공!'이라고 적어줘."

> "이 데이터로 피벗 테이블과 막대 차트를 만들어줘."

> "VBA 매크로를 작성해서 모든 시트의 합계를 계산해줘."

> "엑셀 창을 띄워줘." (백그라운드 → 화면 표시)

## 주의사항

- 작업 전 **다른 엑셀 파일은 모두 닫아주세요** (파일 독점 방지)
- 시스템 트레이에 Excel 아이콘이 생기면 MCP 서버가 정상 동작 중인 것입니다
- 기본 백그라운드 모드가 속도가 빠릅니다. 꼭 필요할 때만 창 표시 요청하세요

## 참고

- [mcp-server-excel GitHub](https://github.com/sbroenne/mcp-server-excel)
- 25개 MCP 도구, 230+ 오퍼레이션 지원
- MIT 라이선스
