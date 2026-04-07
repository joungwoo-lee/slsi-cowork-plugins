# Win Office COM Automation - Skills

## 포함 스킬

| 스킬 | 파일 | 설명 |
|------|------|------|
| `read-secure-office-doc` | `skills/read-secure-office-doc.md` | DRM/암호화된 MS Office 문서를 COM Automation으로 읽어 Markdown 추출 |

## 설치

```powershell
.\setup.ps1
```

`setup.ps1`은 GitHub Release에서 `DocReaderCli.exe`를 `skills/` 폴더에 다운로드한다.
스킬 MD와 바이너리가 같은 디렉토리에 위치하므로 별도 환경변수 설정이 필요 없다.

## 구조

```
win-office-com-automation/
├── SKILL.md              ← 이 파일
├── setup.ps1             ← 바이너리 설치 스크립트
├── skills/
│   ├── read-secure-office-doc.md   ← 스킬 정의
│   └── DocReaderCli.exe            ← 바이너리 (setup.ps1이 설치)
├── DocReaderCli/          ← 소스 코드
│   ├── DocReaderCli.csproj
│   ├── Program.cs
│   ├── ProcessWatchdog.cs
│   └── Readers/
└── README.md
```
