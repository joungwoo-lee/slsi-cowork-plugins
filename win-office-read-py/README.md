# Win Office COM Automation - DRM 문서 리더 (Python)

사내 DRM이 적용된 MS Office 문서(`.docx`, `.xlsx`, `.pptx`)를 Windows COM 자동화로 열고 Markdown으로 추출하는 Python 기반 CLI 툴 및 Claude Code 에이전트 스킬.

이 폴더는 기존 `win-office-read`의 Python 대체 구현이다. 파일 포맷을 직접 파싱하지 않고, 실제 Windows Office 애플리케이션에 attach 해서 DRM이 풀린 내용을 읽는다.

## 구조

```text
win-office-read-py/
├── README.md
├── .gitignore
├── DocReaderCliPy/
│   ├── requirements.txt
│   └── docreader_cli/
│       ├── __init__.py
│       ├── __main__.py
│       ├── main.py
│       ├── markdown.py
│       ├── office_app.py
│       ├── process_watchdog.py
│       └── readers/
│           ├── __init__.py
│           ├── excel_reader.py
│           ├── powerpoint_reader.py
│           └── word_reader.py
└── skills/
    └── win-office-read-py/
        ├── SKILL.md
        ├── setup.ps1
        └── DocReaderCli.cmd
```

## 설치

```powershell
.\setup.ps1
```

`setup.ps1`는 스킬 폴더 안에 `.venv`를 만들고 Python 의존성(`pywin32`, `psutil`)을 설치한다.

## 사용법

```bash
DocReaderCli.cmd --file "C:\path\to\document.docx"
```

- stdout: Markdown 형태의 문서 내용
- stderr: 디버깅 로그 및 에러

## 핵심 설계

- `pywin32`: Word/Excel/PowerPoint COM 자동화
- `DRM Polling`: 복호화 완료까지 최대 15초 대기
- `ProcessWatchdog`: 새로 뜬 Office PID만 추적해서 정리
- `Windows-only`: 사용자 세션에서 실행 중인 실제 Office에 attach
