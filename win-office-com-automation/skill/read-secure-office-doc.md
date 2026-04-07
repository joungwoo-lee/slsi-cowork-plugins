---
name: read-secure-office-doc
description: >
  Windows 로컬 환경에서 사내 DRM이 적용된 MS Office 문서(.docx, .xlsx, .pptx)의 내용을 읽어옵니다.
  COM 객체 자동화를 통해 백그라운드에서 실제 오피스 프로그램을 실행하여 안전하게 텍스트와 구조를 Markdown으로 추출합니다.
---

사용자가 DRM 문서를 읽어달라고 요청하면, 문서의 **절대 경로**(Windows 경로)를 확인한 뒤 아래 명령을 실행한다.

## 실행 명령

```bash
"${DOC_READER_CLI_PATH:-DocReaderCli.exe}" --file "<문서_절대경로>"
```

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
