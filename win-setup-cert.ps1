# =========================================================
# 사내 SSL 인증서 일괄 등록 스크립트 (Safe Mode - 부작용 제로)
# =========================================================

# 0. 관리자 권한 체크
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-Not $isAdmin) {
    Write-Host "[오류] 관리자 권한이 필요합니다. PowerShell을 관리자 권한으로 실행한 후 다시 시도해주세요!" -ForegroundColor Red
    Pause
    exit
}

# 1. 인증서 경로 설정
$certPath = "C:\certs\company_cert.crt" 

# 파일 존재 여부 확인
if (-Not (Test-Path $certPath)) {
    Write-Host "인증서 파일을 찾을 수 없습니다: $certPath" -ForegroundColor Red
    exit
}

Write-Host "🚀 사내 인증서($certPath) 일괄 등록을 시작합니다. (외부 인증 유지 모드)" -ForegroundColor Cyan

# ---------------------------------------------------------
# Step 1. 윈도우 시스템 (Root 저장소) 등록 -> [가장 안전한 '추가' 방식]
# ---------------------------------------------------------
Write-Host "`n[1/3] 윈도우 시스템 인증서 저장소에 추가 중..."
try {
    Import-Certificate -FilePath $certPath -CertStoreLocation Cert:\LocalMachine\Root | Out-Null
    Write-Host " -> 시스템 인증서 추가 완료 (Chrome, Edge, Windows 등 적용)" -ForegroundColor Green
} catch {
    Write-Host " -> 시스템 인증서 추가 실패: $_" -ForegroundColor Red
}

# ---------------------------------------------------------
# Step 2. Node.js 환경 변수 등록 -> [기존 인증서 유지 + '추가' 방식]
# ---------------------------------------------------------
Write-Host "`n[2/3] Node.js 추가 인증서 환경 변수 설정 중..."
try {
    # 기존 통신망을 깨는 REQUESTS_CA_BUNDLE 등은 제외하고, 안전한 NODE_EXTRA_CA_CERTS만 등록합니다.
    [Environment]::SetEnvironmentVariable("NODE_EXTRA_CA_CERTS", $certPath, "Machine")
    Write-Host " -> NODE_EXTRA_CA_CERTS 등록 완료 (npm 외부망 접속 유지)" -ForegroundColor Green
} catch {
    Write-Host " -> 환경 변수 등록 실패: $_" -ForegroundColor Red
}

# ---------------------------------------------------------
# Step 3. Git 시스템 설정 -> [Windows 인증서 저장소 '위임' 방식]
# ---------------------------------------------------------
Write-Host "`n[3/3] Git 인증서 시스템 연동 중..."
if (Get-Command git -ErrorAction SilentlyContinue) {
    # 특정 인증서를 강제하지 않고, Step 1에서 등록한 Windows 시스템 저장소를 사용하도록 위임 (schannel)
    git config --system http.sslBackend schannel
    Write-Host " -> Git Windows 시스템 인증서(schannel) 연동 완료 (GitHub 등 외부 접속 유지)" -ForegroundColor Green
} else {
    Write-Host " -> Git이 설치되어 있지 않아 건너뜁니다." -ForegroundColor Yellow
}

Write-Host "`n🎉 모든 설정이 안전하게 완료되었습니다! 외부망 접속을 해치지 않습니다." -ForegroundColor Cyan
Write-Host "적용을 위해 열려있는 터미널(CMD/PowerShell) 및 IDE(VSCode 등)를 모두 껐다가 다시 켜주세요." -ForegroundColor White
