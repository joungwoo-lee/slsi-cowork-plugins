# Win Office COM Automation - DRM 문서 리더

사내 DRM이 적용된 MS Office 문서(.docx, .xlsx, .pptx 등)를 COM 객체 자동화를 통해 Markdown으로 추출하는 CLI 툴 및 Claude Code 에이전트 스킬.

## 구조

```
win-office-read/
├── README.md
├── skills/
│   └── win-office-read/
│       ├── SKILL.md           # Claude Code 에이전트 스킬 정의
│       ├── setup.ps1          # 릴리즈 zip 설치 스크립트
│       └── DocReaderCli.exe   # setup.ps1 실행 후 이 위치에 배치
└── DocReaderCli/              # C# .NET 8 단일 바이너리 CLI 소스
    ├── build.ps1              # 워크플로와 같은 publish/zip 빌드 스크립트
    ├── DocReaderCli.csproj
    ├── Program.cs
    ├── OleMessageFilter.cs
    ├── ProcessWatchdog.cs
    └── Readers/
        ├── WordReader.cs
        ├── ExcelReader.cs
        ├── ExcelInteropReader.cs
        └── PowerPointReader.cs
```

## 설치

```powershell
.\skills\win-office-read\setup.ps1
```

GitHub Release에서 `DocReaderCli-win-x64.zip`을 내려받아 `skills/win-office-read/`에 풀고, `DocReaderCli.exe`를 같은 디렉터리에 설치한다.
스킬 MD와 바이너리가 같은 디렉토리에 위치하므로 별도 환경변수/PATH 설정이 필요 없다.

## 빌드 (소스에서)

```bash
cd DocReaderCli
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

출력:

- `DocReaderCli/publish/DocReaderCli.exe`
- `DocReaderCli/publish/DocReaderCli-win-x64.zip`

## 사용법

```bash
DocReaderCli.exe --file "C:\path\to\document.docx"
```

엑셀은 기본적으로 interop 엔진을 사용하며, 필요하면 다음처럼 지정할 수 있다.

```bash
DocReaderCli.exe --file "C:\path\to\document.xlsx" --excel-engine interop
```

- stdout: Markdown 형태의 문서 내용
- stderr: 디버깅 로그 및 에러

지원 형식:

- Word/PDF: `.docx`, `.doc`, `.pdf`
- Excel: `.xlsx`, `.xls`
- PowerPoint: `.pptx`, `.ppt`, `.pptm`, `.ppsx`, `.pps`, `.potx`, `.potm`

## 핵심 설계

- **NetOffice 라이브러리**: Office 버전 무관 COM 제어
- **Excel interop 엔진 기본 사용**: NetOffice 대체 경로를 유지하면서 엑셀 호환성 보완
- **DRM Polling**: 복호화 완료까지 최대 15초 대기
- **Watchdog**: 20초 타임아웃 후 좀비 Office 프로세스 강제 종료
- **PID 추적**: 사용자의 기존 Office 프로세스는 보호
