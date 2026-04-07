---
name: read-secure-office-doc
description: >
  Windows 네이티브 환경에서 MS Office 문서(.docx, .xlsx, .pptx)를 읽는 유일한 방법.
  일반 파서(python-docx, openpyxl, python-pptx)로 열리지 않는 DRM/암호화 문서도 처리 가능.
  COM Automation으로 실제 오피스를 백그라운드 실행하여 텍스트를 Markdown으로 추출한다.
  이 스킬은 docx, xlsx, pptx 스킬과 다르다 — 그 스킬들은 WSL/Linux 파서 기반이고, 이 스킬은 Windows COM 기반이다.
  Windows 경로(C:\...)의 오피스 파일을 읽을 때, 또는 DRM/보안 문서를 읽을 때 이 스킬을 사용하라.
---

문서의 **절대 경로**(Windows 경로, 예: `C:\Users\...\file.docx`)를 확인한 뒤 아래 명령을 실행한다.

## 실행 명령

`DocReaderCli.exe`는 이 스킬 파일 바로 옆에 있다. 상대경로로 실행:

```bash
./DocReaderCli.exe --file "<문서_절대경로>"
```

> 작업 디렉토리를 이 스킬 파일이 있는 `skills/` 폴더로 이동한 뒤 실행한다.

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
