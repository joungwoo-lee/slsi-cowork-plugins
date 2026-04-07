---
name: read-secure-office-doc
description: >
  Windows 로컬 환경에서 사내 DRM이 적용된 MS Office 문서(.docx, .xlsx, .pptx)의 내용을 읽어옵니다.
  COM 객체 자동화를 통해 백그라운드에서 실제 오피스 프로그램을 실행하여 안전하게 텍스트와 구조를 Markdown으로 추출합니다.
model: sonnet
---

# read-secure-office-doc Skill

이 스킬은 DRM이 적용된 MS Office 문서를 COM Automation 기반 단일 바이너리(`DocReaderCli.exe`)를 통해 읽어옵니다.

## 사용 조건

- **Windows 전용**: 이 스킬은 Windows 네이티브 환경에서만 동작합니다 (WSL 불가).
- **MS Office 필수**: 대상 PC에 Microsoft Office가 설치되어 있어야 합니다.
- **바이너리 위치**: `DocReaderCli.exe`가 PATH에 있거나, 환경변수 `DOC_READER_CLI_PATH`로 경로를 지정해야 합니다.

## 실행 방법

사용자가 DRM 문서를 읽어달라고 요청하면:

1. 사용자에게 문서의 **절대 경로**(Windows 경로)를 확인합니다.
2. 아래 Bash 명령으로 `DocReaderCli.exe`를 실행합니다.

### 실행 명령

```bash
# 환경변수로 바이너리 경로를 설정한 경우
"${DOC_READER_CLI_PATH:-DocReaderCli.exe}" --file "<문서_절대경로>"

# 예시
DocReaderCli.exe --file "C:\Users\user\Documents\report.docx"
```

### 타임아웃

- 서브프로세스 타임아웃: **30초**
- 바이너리 내부에서도 DRM 복호화 대기 15초 + 워치독 20초가 동작합니다.

### 출력 처리

- **stdout**: 추출된 Markdown 텍스트 → 이 내용을 사용자에게 컨텍스트로 제공
- **stderr**: 디버깅 로그/에러 → 실패 시 원인 분석에 사용

### 종료 코드

| Code | 의미 |
|------|------|
| 0 | 성공 |
| 1 | 인자 오류 (--file 누락) |
| 2 | 파일 없음 |
| 3 | DRM 복호화 타임아웃 |
| 4 | 미지원 파일 형식 |
| 99 | 예기치 않은 오류 |

### 에러 발생 시

- 종료코드 3 (타임아웃): DRM 인증이 필요할 수 있음. 사용자에게 해당 문서를 한번 직접 열어 DRM 인증을 완료한 뒤 재시도하도록 안내.
- 종료코드 99: stderr의 스택트레이스를 확인하여 원인 진단.

## 지원 파일 형식

- `.docx` / `.doc` → Microsoft Word
- `.xlsx` / `.xls` → Microsoft Excel
- `.pptx` / `.ppt` → Microsoft PowerPoint
