---
name: win-office-copy
description: "Windows 네이티브 환경에서 DRM이 걸린 Office 문서(.docx, .doc, .xlsx, .xls, .pptx, .ppt 등)의 DRM을 제거한 100% 동일한 사본 파일을 저장한다. COM Automation으로 실제 Word/Excel/PowerPoint를 실행하여 DRM 인증 후 SaveCopyAs()로 원본과 동일한 형식의 복사본을 생성한다. DRM/보안 문서의 사본이 필요할 때 이 스킬을 사용하라."
---

# 사용법

## 절대 경로 파악

사용자가 파일명이나 상대 경로만 언급한 경우, 실행 전에 PowerShell로 절대 경로를 확인한다.

```powershell
(Get-Item '<파일명 또는 상대경로>').FullName
```

경로를 이미 알고 있거나 사용자가 직접 절대 경로를 제공한 경우 이 단계를 건너뛴다.

## 실행 명령

최초 1회 `setup.ps1`을 실행하면 `DocCopyCli.exe`가 설치되고 사용자 PATH에 등록된다.

`DocCopyCli.exe`가 아직 없거나 명령을 찾지 못하면, 먼저 스킬 폴더 안의 `setup.ps1`을 실행한 뒤 다시 시도한다.

이후 어느 디렉토리에서나 실행:

```bash
# 단일 파일: 같은 폴더에 <원본명>_copy.<확장자>로 저장
DocCopyCli.exe --file "<DRM_문서_절대경로>"

# 단일 파일: 출력 경로 직접 지정
DocCopyCli.exe --file "<DRM_문서_절대경로>" --output "<저장할_경로>"

# 폴더 일괄: 폴더 안의 지원 형식 파일을 모두 DRM 해제 복사
DocCopyCli.exe --file "<폴더_경로>" --all

# 폴더 일괄: 출력 폴더 직접 지정 (기본: <입력폴더>\drm-free\)
DocCopyCli.exe --file "<폴더_경로>" --all --output "<출력_폴더_경로>"
```

- 지원 형식: `.docx`, `.doc`, `.xlsx`, `.xls`, `.pptx`, `.ppt`, `.pptm`, `.ppsx`, `.pps`, `.potx`, `.potm`
- stdout → 저장된 파일의 절대 경로(파일마다 한 줄씩). 사용자에게 경로를 알려준다.
- stderr → 진행 로그/에러. 실패 시 원인 분석용.
- `--all` 모드: 파일별로 성공/실패를 계속 진행하며, 마지막에 성공/실패 수를 요약 출력.
- Excel 기본 엔진: `netoffice` (셸 오픈, DRM 인증 다이얼로그 지원). DRM 없는 파일은 `--excel-engine interop` 사용 가능.

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
