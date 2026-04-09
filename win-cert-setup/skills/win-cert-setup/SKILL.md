---
name: win-cert-setup
description: "AI나 CLI가 사내 SSL 인증서 때문에 HTTPS 연결에 실패할 때 사용하는 Windows 인증서 설치 스킬. 인증서 경로를 아직 모르면 먼저 사용자에게 사내 인증서 파일(.crt/.cer/.pem)의 Windows 절대 경로를 물어보고, 받은 경로로 setup.ps1를 관리자 권한 PowerShell에서 실행해 Windows Root 저장소, NODE_EXTRA_CA_CERTS, Git schannel, Python/CURL/pip CA 번들을 함께 설정한다."
---

# Windows SSL Certificate Setup

사내 SSL 인증서 미설치로 `certificate verify failed`, `self signed certificate in certificate chain`, `unable to get local issuer certificate`, `SSL: CERTIFICATE_VERIFY_FAILED` 같은 오류가 날 때 이 스킬을 사용한다.

## 규칙

1. 사용자가 인증서 경로를 주지 않았다면 먼저 아래처럼 질문한다.

```text
사내 루트 인증서 파일 경로가 필요합니다. Windows에서 접근 가능한 인증서 파일(.crt, .cer, .pem)의 절대 경로를 알려주세요.
예: C:\certs\company_cert.crt
현재 파일이 없다면 어느 경로에 둘지 정해서 알려주시면 그 기준으로 안내하겠습니다.
```

2. 사용자가 준 경로는 그대로 쓰지 말고, 먼저 PowerShell로 존재 여부를 확인한다.

```powershell
Test-Path '<CERT_PATH>'
```

3. 파일이 없으면 사용자가 인증서를 둘 경로를 다시 정하도록 요청한다.

4. 파일이 있으면 관리자 권한 PowerShell에서 같은 디렉토리의 `setup.ps1`를 실행한다.

```powershell
powershell -ExecutionPolicy Bypass -File '<SKILL_DIR>\setup.ps1' -CertPath '<CERT_PATH>'
```

`<SKILL_DIR>`는 현재 `SKILL.md`와 같은 폴더다.

5. 실행 후에는 아래 사항을 사용자에게 알려준다.

- 열려 있는 터미널, VS Code, Claude Code, 기타 AI 도구를 모두 종료 후 다시 실행해야 환경 변수가 반영된다.
- Python `certifi`가 나중에 갱신되면 이 스크립트를 다시 실행해야 할 수 있다.

## 기대 효과

- Windows, Chrome, Edge가 시스템 Root 저장소에서 사내 인증서를 신뢰한다.
- Node.js가 `NODE_EXTRA_CA_CERTS`로 사내 인증서를 추가 신뢰한다.
- Git이 Windows 인증서 저장소(`schannel`)를 사용한다.
- Python `requests`, `pip`, `curl`이 통합 CA 번들을 사용한다.

## 주의

- 이 스킬은 Windows 전용이다.
- 관리자 권한이 없으면 시스템 Root 저장소 등록이 실패한다.
- 사용자에게 인증서 파일을 어느 경로에 둘지 먼저 확인받아야 한다.
