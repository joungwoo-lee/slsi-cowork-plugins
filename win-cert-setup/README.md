# Windows SSL Certificate Setup

AI 도구가 사내 SSL 인증서 때문에 HTTPS 연결에 실패할 때, Windows 시스템/Node.js/Git/Python 환경에 사내 인증서를 설치하는 스킬.

## 구조

```text
win-cert-setup/
├── README.md
└── skills/
    └── win-cert-setup/
        ├── SKILL.md
        └── setup.ps1
```

## 사용 방식

1. SSL 인증서 검증 실패가 발생하면 이 스킬을 사용한다.
2. 스킬은 먼저 사용자에게 사내 인증서 파일의 Windows 절대 경로를 물어본다.
3. 경로를 받은 뒤 `setup.ps1`를 관리자 권한 PowerShell로 실행한다.

예시:

```powershell
powershell -ExecutionPolicy Bypass -File .\skills\win-cert-setup\setup.ps1 -CertPath "C:\certs\company_cert.crt"
```

## 적용 범위

- Windows Root 인증서 저장소
- `NODE_EXTRA_CA_CERTS`
- Git `http.sslBackend schannel`
- Python `certifi` 기반 통합 CA 번들
- `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE`, `pip global.cert`
