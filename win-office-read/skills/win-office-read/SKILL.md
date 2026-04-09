---
name: drm-docx-xlsx
description: "Windows 네이티브 환경에서 DRM이 걸린 .docx 또는 .xlsx 문서를 읽기 위한 스킬. 일반 파서(python-docx, openpyxl)로 열리지 않는 DRM/보안 문서도 COM Automation으로 실제 Word/Excel을 백그라운드 실행하여 Markdown 텍스트로 추출한다. Windows 경로의 DRM/보안 .docx 또는 .xlsx 파일을 읽을 때 이 스킬을 사용하라."
---

# 사용법

## 절대 경로 파악

사용자가 파일명이나 상대 경로만 언급한 경우, 실행 전에 PowerShell로 절대 경로를 확인한다.

```powershell
(Get-Item '<파일명 또는 상대경로>').FullName
```

경로를 이미 알고 있거나 사용자가 직접 절대 경로를 제공한 경우 이 단계를 건너뛴다.

## 실행 명령

최초 1회 `setup.ps1`을 실행하면 `DocReaderCli.exe`가 설치되고 사용자 PATH에 등록된다.

`DocReaderCli.exe`가 아직 없거나 명령을 찾지 못하면, 먼저 스킬 폴더 안의 `setup.ps1`을 실행한 뒤 다시 시도한다.

이후 어느 디렉토리에서나 실행:

```bash
DocReaderCli.exe --file "<DRM_DOCX_또는_XLSX_절대경로>"
```

- 지원 형식: `.docx`, `.doc`, `.xlsx`, `.xls`
- 타임아웃: **30초**
- **stdout** → 추출된 Markdown 텍스트. 사용자에게 컨텍스트로 제공.
- **stderr** → 로그/에러. 실패 시 원인 분석용.

## 종료 코드

| Code | 의미 |
|------|------|
| 0 | 성공 |
| 1 | 인자 오류 (--file 누락) |
| 2 | 파일 없음 |
| 3 | DRM 복호화 타임아웃 — 사용자에게 문서를 직접 한번 열어 DRM 인증 완료 후 재시도 안내 |
| 4 | 미지원 파일 형식 |
| 99 | 예기치 않은 오류 — stderr 스택트레이스 확인 |
