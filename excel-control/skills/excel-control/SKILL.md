---
name: excel-control
description: |
  Microsoft Excel 자동화 스킬. mcp-server-excel(stdio)을 통해 엑셀 워크북을 읽기, 쓰기, 서식, 차트, 피벗, 수식, VBA, Power Query 등 전체 제어.
  Trigger: "엑셀 열어", "Excel 파일 만들어", "셀에 값 넣어", "차트 그려", "피벗 테이블", "엑셀 자동화",
  "스프레드시트 작업", "워크북", "워크시트", "엑셀 서식", "엑셀 수식", "VBA 매크로",
  또는 mcp-server-excel MCP 도구를 사용해야 하는 모든 엑셀 관련 요청.
---

# Excel Control Skill

mcp-server-excel MCP 서버(stdio)를 통해 Windows의 실제 Microsoft Excel을 COM 자동화로 제어합니다.

## 셋업

PowerShell에서 최초 1회 실행:
```powershell
powershell -ExecutionPolicy Bypass -File "<SCRIPTS_DIR>\setup_excel_mcp.ps1"
```

`<SCRIPTS_DIR>`은 이 SKILL.md 파일과 같은 디렉토리의 `scripts\` 폴더입니다.

## 사전 조건

- **Windows** 환경 (Excel COM 자동화 필수)
- **Microsoft Excel 2016+** 설치
- setup 스크립트 실행 완료 (.mcp.json에 경로 자동 설정됨)

## MCP 도구 카테고리 (25개 도구, 230+ 오퍼레이션)

| 카테고리 | 주요 기능 |
|----------|-----------|
| **Files** | 워크북 열기/닫기/저장, 세션 관리 |
| **Ranges** | 셀 값 읽기/쓰기, 수식, 서식, 유효성 검사, 보호 |
| **Worksheets** | 시트 생성/삭제/이름변경, 색상, 가시성 |
| **Excel Tables** | 테이블 생성, 필터링, 정렬, 구조적 참조 |
| **PivotTables** | 피벗 테이블 생성, 필드 배치, 집계 |
| **Charts** | 차트 생성, 시리즈, 서식, 데이터 레이블, 추세선 |
| **VBA** | 매크로 모듈 관리, 실행 |
| **Power Query** | M 코드 관리, 워크플로, 로드 대상 설정 |
| **Data Model/DAX** | 측정값, 관계, 모델 구조 |
| **Named Ranges** | 이름 정의, 매개변수 설정 |
| **Connections** | OLEDB/ODBC 연결, 새로고침 |
| **Slicers** | 인터랙티브 필터링 |
| **Conditional Formatting** | 조건부 서식 규칙 |
| **Calculation Mode** | 계산 모드 설정, 재계산 트리거 |
| **Screenshot** | PNG 캡처 (LLM 검증용) |
| **Window Management** | 엑셀 창 표시/숨김, 정렬, 위치 |

## 작업 규칙

1. **엑셀 창 표시**: 사용자가 작업 과정을 보고 싶어하면 Window Management 도구로 엑셀 창을 표시한다.
2. **파일 독점**: 작업 시작 전, 대상 엑셀 파일이 다른 프로세스에 열려 있지 않아야 한다. 충돌 가능성을 사용자에게 안내한다.
3. **저장 확인**: 대규모 변경 후에는 반드시 저장 여부를 사용자에게 확인한다.
4. **스크린샷 검증**: 복잡한 서식이나 차트 작업 후 Screenshot 도구로 결과를 캡처하여 사용자에게 보여준다.
5. **에러 처리**: MCP 도구 호출 실패 시, 에러 메시지를 사용자에게 전달하고 대안을 제시한다.

## 작업 흐름 예시

### 새 워크북 생성 및 데이터 입력
1. Files 도구로 새 워크북 생성
2. Ranges 도구로 셀에 값/수식 입력
3. Ranges 도구로 서식 적용 (폰트, 색상, 테두리)
4. Files 도구로 저장

### 데이터 분석 (피벗 + 차트)
1. Files 도구로 기존 워크북 열기
2. Excel Tables 도구로 데이터를 테이블로 변환
3. PivotTables 도구로 피벗 테이블 생성
4. Charts 도구로 차트 생성
5. Screenshot 도구로 결과 캡처

### VBA 매크로 작업
1. Files 도구로 .xlsm 워크북 열기
2. VBA 도구로 모듈 생성/편집
3. VBA 도구로 매크로 실행
4. Files 도구로 매크로 포함 저장

## 주의사항

- 이 스킬은 **Windows 환경에서만** 동작합니다 (Excel COM 자동화).
- 기본적으로 엑셀은 **백그라운드**에서 동작합니다. 실시간 확인이 필요하면 창 표시를 요청하세요.
- 대용량 파일 작업 시 성능을 위해 Calculation Mode를 수동으로 전환할 수 있습니다.
