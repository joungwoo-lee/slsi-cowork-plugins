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
5. Claude Code / Claude Desktop / VS Code 설정 파일에 자동 등록
6. **stdio 핸드셰이크 테스트**로 실제 동작 검증

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

## 동작 원리

```
AI 에이전트 ──stdio──> mcp-excel.exe ──COM──> Microsoft Excel
   (JSON-RPC)            (MCP Server)         (실제 엑셀 프로세스)
```

- AI 에이전트가 `.mcp.json`을 읽고 `mcp-excel.exe`를 자식 프로세스로 실행
- stdin/stdout으로 JSON-RPC 메시지 교환 (MCP 프로토콜)
- `mcp-excel.exe`가 Excel COM 자동화로 실제 엑셀을 제어

## 사용 예시

AI 에이전트 프롬프트:

> "새로운 엑셀 파일을 열고, A1 셀에 '테스트', A2 셀에 '성공!'이라고 적어줘."

> "이 데이터로 피벗 테이블과 막대 차트를 만들어줘."

> "VBA 매크로를 작성해서 모든 시트의 합계를 계산해줘."

> "엑셀 창을 띄워줘." (백그라운드 → 화면 표시)

## 참고

- [mcp-server-excel GitHub](https://github.com/sbroenne/mcp-server-excel)
- 25개 MCP 도구, 230+ 오퍼레이션 지원
- MIT 라이선스
