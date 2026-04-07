# Win Office COM Automation - DRM 문서 리더

사내 DRM이 적용된 MS Office 문서(.docx, .xlsx, .pptx)를 COM 객체 자동화를 통해 Markdown으로 추출하는 CLI 툴 및 Claude Code 에이전트 스킬.

## 구조

```
win-office-com-automation/
├── SKILL.md               # 스킬 목록 및 설치 가이드
├── setup.ps1              # 바이너리 설치 스크립트
├── skills/
│   ├── read-secure-office-doc.md  # Claude Code 에이전트 스킬 정의
│   └── DocReaderCli.exe           # 바이너리 (setup.ps1이 설치)
└── DocReaderCli/              # C# .NET 8 단일 바이너리 CLI 소스
    ├── DocReaderCli.csproj
    ├── Program.cs
    ├── ProcessWatchdog.cs     # 좀비 프로세스 감시/강제종료
    └── Readers/
        ├── WordReader.cs      # .docx/.doc 추출
        ├── ExcelReader.cs     # .xlsx/.xls 추출
        └── PowerPointReader.cs # .pptx/.ppt 추출
```

## 설치

```powershell
.\setup.ps1
```

GitHub Release에서 `DocReaderCli.exe`를 `skills/` 폴더에 다운로드한다.
스킬 MD와 바이너리가 같은 디렉토리에 위치하므로 별도 환경변수/PATH 설정이 필요 없다.

## 빌드 (소스에서)

```bash
cd DocReaderCli
dotnet publish -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true
```

출력: `DocReaderCli/publish/DocReaderCli.exe` (단일 실행 파일, .NET 런타임 불필요)

## 사용법

```bash
DocReaderCli.exe --file "C:\path\to\document.docx"
```

- stdout: Markdown 형태의 문서 내용
- stderr: 디버깅 로그 및 에러

## 핵심 설계

- **NetOffice 라이브러리**: Office 버전 무관 COM 제어
- **DRM Polling**: 복호화 완료까지 최대 15초 대기
- **Watchdog**: 20초 타임아웃 후 좀비 Office 프로세스 강제 종료
- **PID 추적**: 사용자의 기존 Office 프로세스는 보호
