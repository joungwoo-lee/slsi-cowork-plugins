# Excel Control Plugin

mcp-server-excel을 stdio 방식으로 연동하여 Microsoft Excel을 AI 에이전트에서 직접 제어하는 플러그인입니다.

## 요구사항

- Windows
- Microsoft Excel 2016 이상
- PowerShell 5.1+

## 설치

PowerShell에서 실행:
```powershell
powershell -ExecutionPolicy Bypass -File "excel-control\skills\excel-control\scripts\setup_excel_mcp.ps1"
```

셋업 스크립트가 자동으로:
1. mcp-server-excel 실행 파일(mcp-excel.exe)을 GitHub에서 다운로드
2. `%USERPROFILE%\ExcelMcp\`에 설치
3. `.mcp.json`에 stdio MCP 서버 경로를 설정
4. (선택) Claude Code `settings.json` 및 OpenCode `config.json`에도 등록
5. stdio 통신 테스트

## 구조

```
excel-control/
├── .claude-plugin/
│   └── plugin.json               # 플러그인 메타데이터
├── .mcp.json                     # MCP 서버 stdio 설정
├── skills/
│   └── excel-control/
│       ├── SKILL.md              # 스킬 정의 및 사용법
│       └── scripts/
│           └── setup_excel_mcp.ps1  # 원클릭 설치 스크립트 (PowerShell)
└── README.md
```

## 사용법

Claude Code 또는 호환 AI 에이전트(OpenCode 등)에서:

> "새로운 엑셀 파일을 열고, A1 셀에 '테스트', A2 셀에 '성공!'이라고 적어줘."

> "이 데이터로 피벗 테이블과 막대 차트를 만들어줘."

> "VBA 매크로를 작성해서 모든 시트의 합계를 계산해줘."

## 참고

- [mcp-server-excel GitHub](https://github.com/sbroenne/mcp-server-excel)
- 25개 MCP 도구, 230+ 오퍼레이션 지원
- MIT 라이선스
