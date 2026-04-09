param(
    [Parameter(Mandatory = $true)]
    [string]$CertPath
)

# =========================================================
# 사내 SSL 인증서 일괄 등록 스크립트
# - Windows Root 저장소 등록
# - Node.js NODE_EXTRA_CA_CERTS 설정
# - Git schannel 설정
# - Python/CURL/pip 통합 CA 번들 생성
# =========================================================

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-Not $isAdmin) {
    Write-Host "[오류] 관리자 권한이 필요합니다. PowerShell을 관리자 권한으로 실행해주세요!" -ForegroundColor Red
    exit 1
}

$resolvedCertPath = $null
try {
    $resolvedCertPath = (Resolve-Path -Path $CertPath -ErrorAction Stop).Path
} catch {
    Write-Host "인증서 파일을 찾을 수 없습니다: $CertPath" -ForegroundColor Red
    exit 1
}

Write-Host "사내 인증서($resolvedCertPath) 일괄 등록을 시작합니다..." -ForegroundColor Cyan

Write-Host "`n[1/4] 윈도우 시스템 인증서 저장소에 등록 중..."
try {
    Import-Certificate -FilePath $resolvedCertPath -CertStoreLocation Cert:\LocalMachine\Root | Out-Null
    Write-Host " -> 시스템 인증서(Windows, Chrome, Edge) 등록 완료" -ForegroundColor Green
} catch {
    Write-Host " -> 시스템 인증서 등록 실패: $_" -ForegroundColor Red
}

Write-Host "`n[2/4] Node.js 추가 인증서 환경 변수 설정 중..."
try {
    [Environment]::SetEnvironmentVariable("NODE_EXTRA_CA_CERTS", $resolvedCertPath, "Machine")
    Write-Host " -> NODE_EXTRA_CA_CERTS 등록 완료 (외부망 접속 유지)" -ForegroundColor Green
} catch {
    Write-Host " -> 환경 변수 등록 실패: $_" -ForegroundColor Red
}

Write-Host "`n[3/4] Git 인증서 시스템 연동 중..."
if (Get-Command git -ErrorAction SilentlyContinue) {
    git config --system http.sslBackend schannel
    Write-Host " -> Git Windows 시스템 인증서(schannel) 연동 완료" -ForegroundColor Green
} else {
    Write-Host " -> Git이 설치되어 있지 않아 건너뜁니다." -ForegroundColor Yellow
}

Write-Host "`n[4/4] Python 통합 인증서 번들 생성 및 설정 중..."
$combinedCertPath = Join-Path -Path ([System.IO.Path]::GetDirectoryName($resolvedCertPath)) -ChildPath "company_combined_ca.pem"
$pythonCertPath = python -c "import certifi; print(certifi.where())" 2>$null

if ($LASTEXITCODE -eq 0 -and $pythonCertPath -and (Test-Path $pythonCertPath)) {
    try {
        $baseCerts = Get-Content -Path $pythonCertPath -Raw
        $companyCert = Get-Content -Path $resolvedCertPath -Raw

        if ($baseCerts.Contains($companyCert.Trim())) {
            $combinedCerts = $baseCerts
            Write-Host " -> (이미 파이썬 기본 인증서에 사내 인증서가 포함되어 있습니다.)" -ForegroundColor Gray
        } else {
            $combinedCerts = $baseCerts + "`n`n" + $companyCert
        }

        $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllText($combinedCertPath, $combinedCerts, $utf8NoBom)

        [Environment]::SetEnvironmentVariable("REQUESTS_CA_BUNDLE", $combinedCertPath, "Machine")
        [Environment]::SetEnvironmentVariable("CURL_CA_BUNDLE", $combinedCertPath, "Machine")

        if (Get-Command pip -ErrorAction SilentlyContinue) {
            pip config set global.cert $combinedCertPath 2>$null | Out-Null
        }

        Write-Host " -> 통합 CA 번들($combinedCertPath) 생성 및 환경 변수 등록 완료" -ForegroundColor Green
        Write-Host "    * 주의: 향후 pip 업그레이드로 certifi가 갱신되면 이 스크립트를 다시 실행해야 할 수 있습니다." -ForegroundColor Yellow
    } catch {
        Write-Host " -> 통합 인증서 번들 생성 중 오류 발생: $_" -ForegroundColor Red
    }
} else {
    Write-Host " -> Python이 설치되어 있지 않거나 certifi 모듈이 없어 건너뜁니다." -ForegroundColor Yellow
}

Write-Host "`n모든 설정이 완료되었습니다!" -ForegroundColor Cyan
Write-Host "변경 사항을 적용하려면 열려 있는 터미널과 VS Code, Claude Code 등을 모두 종료 후 다시 실행해주세요." -ForegroundColor White
