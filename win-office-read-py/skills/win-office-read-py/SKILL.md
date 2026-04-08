---
name: win-office-read-py
description: "Windows 네이티브 환경에서 MS Office 문서(.docx, .xlsx, .pptx)를 Python COM 자동화로 읽는다. 일반 파서(python-docx, openpyxl, python-pptx)로 열리지 않는 DRM/보안 문서도 실제 Office 앱에 attach 해서 Markdown으로 추출한다. Windows 경로의 오피스 파일을 읽거나 DRM 문서를 읽을 때 이 스킬을 사용하라."
---

# 사용법

문서의 **절대 경로**(Windows 경로, 예: `C:\Users\...\file.docx`)를 확인한 뒤 아래 명령을 실행한다.

## 실행 명령

필요하면 먼저 이 폴더에서 `setup.ps1`를 실행해 `.venv`와 Python 의존성을 준비한다.

`DocReaderCli.cmd`는 이 스킬 파일 바로 옆에 있다. 상대경로로 실행:

```bash
./DocReaderCli.cmd --file "<문서_절대경로>"
```

> 작업 디렉토리를 이 스킬 파일이 있는 `skills/win-office-read-py/` 폴더로 이동한 뒤 실행한다.

- 타임아웃: **30초**
- **stdout** -> 추출된 Markdown 텍스트. 사용자에게 컨텍스트로 제공.
- **stderr** -> 로그/에러. 실패 시 원인 분석용.

## 종료 코드

| Code | 의미 |
|------|------|
| 0 | 성공 |
| 1 | 인자 오류 (`--file` 누락) |
| 2 | 파일 없음 |
| 3 | DRM 복호화 타임아웃 |
| 4 | 미지원 파일 형식 |
| 99 | 예기치 않은 오류 또는 비-Windows 환경 |
