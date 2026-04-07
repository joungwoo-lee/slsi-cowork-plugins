# =========================================================
# 사내 SSL 인증서 일괄 등록 스크립트 (Enterprise Final Version)
# - 특징: 외부망 인증 유지, 중복 실행 방지(멱등성 보장), Python 완벽 지원
# =========================================================

# 0. 관리자 권한 체크
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-Not $isAdmin) {
    Write-Host "[오류] 관리자 권한이 필요합니다. PowerShell을 관리자 권한으로 실행해주세요!" -ForegroundColor Red
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

Write-Host "🚀 사내 인증서($certPath) 일괄 등록을 시작합니다..." -ForegroundColor Cyan

# ---------------------------------------------------------
# Step 1. 윈도우 시스템 (Root 저장소) 등록 -> [추가 방식]
# ---------------------------------------------------------
Write-Host "`n[1/4] 윈도우 시스템 인증서 저장소에 등록 중..."
try {
    # 윈도우는 자체적으로 중복 등록을 방지하므로 여러 번 실행해도 안전합니다.
    Import-Certificate -FilePath $certPath -CertStoreLocation Cert:\LocalMachine\Root | Out-Null
    Write-Host " -> 시스템 인증서(Windows, Chrome, Edge) 등록 완료" -ForegroundColor Green
} catch {
    Write-Host " -> 시스템 인증서 등록 실패: $_" -ForegroundColor Red
}

# ---------------------------------------------------------
# Step 2. Node.js 환경 변수 등록 -> [안전한 추가 방식]
# ---------------------------------------------------------
Write-Host "`n[2/4] Node.js 추가 인증서 환경 변수 설정 중..."
try {
    [Environment]::SetEnvironmentVariable("NODE_EXTRA_CA_CERTS", $certPath, "Machine")
    Write-Host " -> NODE_EXTRA_CA_CERTS 등록 완료 (외부망 접속 유지)" -ForegroundColor Green
} catch {
    Write-Host " -> 환경 변수 등록 실패: $_" -ForegroundColor Red
}

# ---------------------------------------------------------
# Step 3. Git 시스템 설정 -> [Windows 시스템 연동 방식]
# ---------------------------------------------------------
Write-Host "`n[3/4] Git 인증서 시스템 연동 중..."
if (Get-Command git -ErrorAction SilentlyContinue) {
    git config --system http.sslBackend schannel
    Write-Host " -> Git Windows 시스템 인증서(schannel) 연동 완료" -ForegroundColor Green
} else {
    Write-Host " -> Git이 설치되어 있지 않아 건너뜁니다." -ForegroundColor Yellow
}

# ---------------------------------------------------------
# Step 4. Python & CURL을 위한 '통합 CA 번들' 생성 및 적용
# ---------------------------------------------------------
Write-Host "`n[4/4] Python 통합 인증서 번들 생성 및 설정 중..."
$combinedCertPath = "C:\certs\company_combined_ca.pem"

# 파이썬에서 기본 퍼블릭 인증서 경로 가져오기
$pythonCertPath = python -c "import certifi; print(certifi.where())" 2>$null

if ($LASTEXITCODE -eq 0 -and (Test-Path $pythonCertPath)) {
    try {
        # 문자열(Raw) 형태로 파일 읽어오기
        $baseCerts = Get-Content -Path $pythonCertPath -Raw
        $companyCert = Get-Content -Path $certPath -Raw
        
        # 중복 방지 로직: 원본에 이미 사내 인증서가 포함되어 있는지 확인
        if ($baseCerts.Contains($companyCert.Trim())) {
            $combinedCerts = $baseCerts
            Write-Host " -> (이미 파이썬 기본 인증서에 사내 인증서가 포함되어 있습니다.)" -ForegroundColor Gray
        } else {
            $combinedCerts = $baseCerts + "`n" + $companyCert
        }
        
        # 통합 인증서 파일 생성 (항상 덮어쓰기 설정)
        Set-Content -Path $combinedCertPath -Value $combinedCerts -Encoding UTF8
        
        # Python 및 CURL이 통합 인증서를 바라보도록 환경 변수 덮어쓰기
        # (통합 파일에는 퍼블릭 인증서도 들어있으므로 외부망 접속이 끊기지 않음)
        [Environment]::SetEnvironmentVariable("REQUESTS_CA_BUNDLE", $combinedCertPath, "Machine")
        [Environment]::SetEnvironmentVariable("CURL_CA_BUNDLE", $combinedCertPath, "Machine")
        
        Write-Host " -> 통합 CA 번들($combinedCertPath) 생성 및 환경 변수 등록 완료!" -ForegroundColor Green
    } catch {
        Write-Host " -> 통합 인증서 번들 생성 중 오류 발생: $_" -ForegroundColor Red
    }
} else {
    Write-Host " -> Python이 설치되어 있지 않거나 certifi 모듈이 없어 건너뜁니다." -ForegroundColor Yellow
}

# ---------------------------------------------------------
# 마무리
# ---------------------------------------------------------
Write-Host "`n🎉 모든 설정이 완벽하게 완료되었습니다!" -ForegroundColor Cyan
Write-Host "변경 사항(환경 변수 등)을 적용하려면 열려있는 터미널과 VSCode 등을 모두 껐다가 다시 켜주세요." -ForegroundColor White
