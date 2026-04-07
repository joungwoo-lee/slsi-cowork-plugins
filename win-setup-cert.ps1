# =========================================================
# 사내 SSL 인증서 일괄 등록 스크립트
# 주의: 반드시 관리자 권한으로 실행하세요!
# =========================================================

# 1. 여기에 사내 인증서의 절대 경로를 입력하세요.
# (경로에 한글이나 공백이 없는 곳을 추천합니다. 예: C:\certs\company.crt)
$certPath = "C:\certs\company_cert.crt" 

# 파일 존재 여부 확인
if (-Not (Test-Path $certPath)) {
    Write-Host "인증서 파일을 찾을 수 없습니다: $certPath" -ForegroundColor Red
    exit
}

Write-Host "🚀 사내 인증서($certPath) 일괄 등록을 시작합니다..." -ForegroundColor Cyan

# ---------------------------------------------------------
# Step 1. 윈도우 시스템 (Root 저장소) 등록
# (Chrome, Edge, 윈도우 자체 시스템 용)
# ---------------------------------------------------------
Write-Host "`n[1/4] 윈도우 시스템 인증서 저장소에 등록 중..."
try {
    Import-Certificate -FilePath $certPath -CertStoreLocation Cert:\LocalMachine\Root | Out-Null
    Write-Host " -> 시스템 인증서 등록 완료" -ForegroundColor Green
} catch {
    Write-Host " -> 시스템 인증서 등록 실패 (관리자 권한인지 확인하세요)" -ForegroundColor Red
}

# ---------------------------------------------------------
# Step 2. 환경 변수 등록
# (Python - requests/urllib, Node.js, 기타 CURL 기반 도구 용)
# ---------------------------------------------------------
Write-Host "`n[2/4] 시스템 환경 변수 설정 중 (Python, Node.js 등)..."
try {
    # 'Machine' 레벨은 시스템 환경 변수를 의미합니다.
    [Environment]::SetEnvironmentVariable("REQUESTS_CA_BUNDLE", $certPath, "Machine")
    [Environment]::SetEnvironmentVariable("CURL_CA_BUNDLE", $certPath, "Machine")
    [Environment]::SetEnvironmentVariable("NODE_EXTRA_CA_CERTS", $certPath, "Machine")
    Write-Host " -> 환경 변수(REQUESTS_CA_BUNDLE, CURL_CA_BUNDLE, NODE_EXTRA_CA_CERTS) 등록 완료" -ForegroundColor Green
} catch {
    Write-Host " -> 환경 변수 등록 실패" -ForegroundColor Red
}

# ---------------------------------------------------------
# Step 3. npm 글로벌 설정
# ---------------------------------------------------------
Write-Host "`n[3/4] npm 인증서 설정 중..."
if (Get-Command npm -ErrorAction SilentlyContinue) {
    # npm 글로벌 설정으로 cafile 지정
    npm config set cafile $certPath -g
    Write-Host " -> npm cafile 설정 완료" -ForegroundColor Green
} else {
    Write-Host " -> npm이 설치되어 있지 않거나 환경 변수에 없어 건너뜁니다." -ForegroundColor Yellow
}

# ---------------------------------------------------------
# Step 4. Git 시스템 설정
# ---------------------------------------------------------
Write-Host "`n[4/4] Git 인증서 설정 중..."
if (Get-Command git -ErrorAction SilentlyContinue) {
    # --system 옵션을 주어 해당 PC의 모든 사용자 및 레포지토리에 적용
    git config --system http.sslCAInfo $certPath
    Write-Host " -> Git http.sslCAInfo 설정 완료" -ForegroundColor Green
} else {
    Write-Host " -> Git이 설치되어 있지 않거나 환경 변수에 없어 건너뜁니다." -ForegroundColor Yellow
}

Write-Host "`n🎉 모든 설정이 완료되었습니다! 열려있는 터미널(CMD/PowerShell) 및 VSCode 등을 모두 껐다가 다시 켜주세요." -ForegroundColor Cyan
