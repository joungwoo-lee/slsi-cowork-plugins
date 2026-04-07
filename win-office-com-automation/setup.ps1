<#
.SYNOPSIS
    DocReaderCli 셋업 스크립트 - GitHub Release에서 바이너리를 다운로드하여 설치합니다.

.DESCRIPTION
    1. GitHub Release에서 최신 DocReaderCli.exe를 다운로드
    2. 설치 디렉토리에 배치
    3. PATH 환경변수에 등록
    4. 환경변수 DOC_READER_CLI_PATH 설정

.EXAMPLE
    # PowerShell에서 실행 (관리자 권한 불필요)
    .\setup.ps1

    # 특정 버전 설치
    .\setup.ps1 -Version v1.0.0
#>

param(
    [string]$Version = "latest",
    [string]$InstallDir = "$env:LOCALAPPDATA\DocReaderCli"
)

$ErrorActionPreference = "Stop"
$RepoOwner = "joungwoo-lee"
$RepoName = "slsi-cowork-plugins"
$BinaryName = "DocReaderCli.exe"

Write-Host "=== DocReaderCli Setup ===" -ForegroundColor Cyan

# 1. Resolve download URL
if ($Version -eq "latest") {
    Write-Host "[1/4] Fetching latest release info..." -ForegroundColor Yellow
    $releaseUrl = "https://api.github.com/repos/$RepoOwner/$RepoName/releases/latest"
    try {
        $release = Invoke-RestMethod -Uri $releaseUrl -Headers @{ "User-Agent" = "DocReaderCli-Setup" }
        $asset = $release.assets | Where-Object { $_.name -eq $BinaryName } | Select-Object -First 1
        if (-not $asset) {
            throw "Release asset '$BinaryName' not found in latest release."
        }
        $downloadUrl = $asset.browser_download_url
        $Version = $release.tag_name
    }
    catch {
        Write-Host "Error: Failed to fetch release info. $_" -ForegroundColor Red
        exit 1
    }
}
else {
    $downloadUrl = "https://github.com/$RepoOwner/$RepoName/releases/download/$Version/$BinaryName"
}

Write-Host "  Version : $Version" -ForegroundColor Gray
Write-Host "  URL     : $downloadUrl" -ForegroundColor Gray

# 2. Create install directory
Write-Host "[2/4] Preparing install directory..." -ForegroundColor Yellow
if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    Write-Host "  Created: $InstallDir" -ForegroundColor Gray
}
else {
    Write-Host "  Exists:  $InstallDir" -ForegroundColor Gray
}

# 3. Download binary
$destPath = Join-Path $InstallDir $BinaryName
Write-Host "[3/4] Downloading $BinaryName..." -ForegroundColor Yellow

try {
    # Use TLS 1.2+ for GitHub
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

    $webClient = New-Object System.Net.WebClient
    $webClient.Headers.Add("User-Agent", "DocReaderCli-Setup")
    $webClient.DownloadFile($downloadUrl, $destPath)

    $fileSize = (Get-Item $destPath).Length / 1MB
    Write-Host "  Downloaded: $destPath ($([math]::Round($fileSize, 1)) MB)" -ForegroundColor Gray
}
catch {
    Write-Host "Error: Download failed. $_" -ForegroundColor Red
    exit 1
}

# 4. Register PATH and environment variable (User scope, no admin needed)
Write-Host "[4/4] Configuring environment..." -ForegroundColor Yellow

# Add to PATH if not already present
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($userPath -notlike "*$InstallDir*") {
    [Environment]::SetEnvironmentVariable("PATH", "$userPath;$InstallDir", "User")
    Write-Host "  Added to PATH (User): $InstallDir" -ForegroundColor Gray
}
else {
    Write-Host "  PATH already contains: $InstallDir" -ForegroundColor Gray
}

# Set DOC_READER_CLI_PATH
[Environment]::SetEnvironmentVariable("DOC_READER_CLI_PATH", $destPath, "User")
Write-Host "  Set DOC_READER_CLI_PATH = $destPath" -ForegroundColor Gray

# Also update current session
$env:PATH = "$env:PATH;$InstallDir"
$env:DOC_READER_CLI_PATH = $destPath

# Done
Write-Host ""
Write-Host "=== Setup Complete ===" -ForegroundColor Green
Write-Host "  Binary  : $destPath"
Write-Host "  Version : $Version"
Write-Host ""
Write-Host "Usage:" -ForegroundColor Cyan
Write-Host "  DocReaderCli.exe --file `"C:\path\to\document.docx`""
Write-Host ""
Write-Host "NOTE: Restart your terminal or run the following to use immediately:" -ForegroundColor Yellow
Write-Host "  `$env:PATH += `";$InstallDir`""
