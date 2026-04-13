---
name: win-office-unlock
description: "Windows 네이티브 환경에서 DRM이 걸린 Office 문서(.docx, .doc, .xlsx, .xls, .pptx, .ppt 등)를 읽어 DRM 없는 출력 파일로 다시 저장한다. 읽은 내용은 같은 basename의 Markdown 파일로도 저장하며, Word/Excel은 새 OOXML 문서를 직접 생성해 저장한다. DRM/보안 문서의 내용을 재저장해야 할 때 이 스킬을 사용하라."
---

# 사용법

## 절대 경로 파악

사용자가 파일명이나 상대 경로만 언급한 경우, 실행 전에 PowerShell로 절대 경로를 확인한다.

```powershell
(Get-Item '<파일명 또는 상대경로>').FullName
```

경로를 이미 알고 있거나 사용자가 직접 절대 경로를 제공한 경우 이 단계를 건너뛴다.

## 실행 명령

최초 1회 `setup.ps1`을 실행하면 `DocUnlockCli.exe`가 설치되고 사용자 PATH에 등록된다.

`DocUnlockCli.exe`가 아직 없거나 명령을 찾지 못하면, 먼저 스킬 폴더 안의 `setup.ps1`을 실행한 뒤 다시 시도한다.

이후 어느 디렉토리에서나 실행:

```bash
# 단일 파일: 같은 폴더에 <원본명>_unlock.<확장자>로 저장
DocUnlockCli.exe --file "<DRM_문서_절대경로>"

# 단일 파일: 출력 경로 직접 지정
DocUnlockCli.exe --file "<DRM_문서_절대경로>" --output "<저장할_경로>"

# 폴더 일괄: 폴더 안의 지원 형식 파일을 모두 DRM 해제 결과로 저장
DocUnlockCli.exe --file "<폴더_경로>" --all

# 폴더 일괄: 출력 폴더 직접 지정 (기본: <입력폴더>\drm-free\)
DocUnlockCli.exe --file "<폴더_경로>" --all --output "<출력_폴더_경로>"
```

- 지원 형식: `.docx`, `.doc`, `.xlsx`, `.xls`, `.pptx`, `.ppt`, `.pptm`, `.ppsx`, `.pps`, `.potx`, `.potm`
- 지원 형식: `.docx`, `.doc`, `.xlsx`, `.xls`, `.pptx`, `.ppt`, `.pptm`, `.ppsx`, `.pps`, `.potx`, `.potm`
- stdout → 저장된 파일의 절대 경로(파일마다 한 줄씩). 에이전트는 이 경로를 파싱하여 사용자에게 알려준다.
- stderr → 진행 로그/에러. 실패 시 원인 분석용. 에이전트는 stderr를 직접 사용자에게 표시하지 말고 오류 분석에만 활용한다.
- Word/Excel은 같은 출력 폴더에 `<원본명>.md`를 함께 만든다. 내용 확인용 덤프다.
- `.doc` 입력은 `.docx`, `.xls` 입력은 `.xlsx`로 재생성된다.
- `--all` 모드: 파일별로 성공/실패를 계속 진행하며, stderr 마지막 줄에 `Done: N succeeded, N failed.` 요약 출력.
- Excel 기본 엔진: `netoffice` (셸 오픈, DRM 인증 다이얼로그 지원). DRM 없는 파일은 `--excel-engine interop` 사용 가능.

## --all 모드 결과 처리

```bash
# stdout 한 줄 = 성공한 파일 경로 1개
DocUnlockCli.exe --file "<폴더>" --all
```

에이전트는 실행 후:
1. stdout의 각 줄 = 성공한 출력 파일 경로 → 사용자에게 목록으로 안내
2. stderr 마지막 줄의 `Done: N succeeded, N failed.` → 요약으로 전달
3. 실패한 파일이 있으면 stderr에서 `TIMEOUT` / `FAILED` 줄을 찾아 원인 분석 후 안내

## DRM 인증이 필요한 경우

종료 코드 3 (타임아웃) 발생 시: 해당 문서를 사용자가 직접 한 번 열어 DRM 인증을 완료한 뒤 재시도하도록 안내한다.

## 종료 코드

| Code | 의미 |
|------|------|
| 0 | 성공 (stdout에 저장 경로 출력) |
| 1 | 인자 오류 (--file 누락) |
| 2 | 파일 없음 |
| 3 | DRM 복호화 타임아웃 — 사용자에게 문서를 직접 한번 열어 DRM 인증 완료 후 재시도 안내 |
| 4 | 미지원 파일 형식 |
| 99 | 예기치 않은 오류 — stderr 스택트레이스 확인 |
