<#
.SYNOPSIS
    DocReaderCli 셋업 - GitHub Release에서 바이너리를 skills/ 폴더에 다운로드합니다.

.EXAMPLE
    .\setup.ps1
    .\setup.ps1 -Version v1.0.0
#>

param(
    [string]$Version = "latest"
)

$ErrorActionPreference = "Stop"
$RepoOwner = "joungwoo-lee"
$RepoName = "slsi-cowork-plugins"
$BinaryName = "DocReaderCli.exe"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallDir = Join-Path $ScriptDir "skills"

Write-Host "=== DocReaderCli Setup ===" -ForegroundColor Cyan

# 1. Resolve download URL
if ($Version -eq "latest") {
    Write-Host "[1/2] Fetching latest release..." -ForegroundColor Yellow
    $releaseUrl = "https://api.github.com/repos/$RepoOwner/$RepoName/releases/latest"
    try {
        $release = Invoke-RestMethod -Uri $releaseUrl -Headers @{ "User-Agent" = "DocReaderCli-Setup" }
        $asset = $release.assets | Where-Object { $_.name -eq $BinaryName } | Select-Object -First 1
        if (-not $asset) { throw "Release asset '$BinaryName' not found." }
        $downloadUrl = $asset.browser_download_url
        $Version = $release.tag_name
    }
    catch {
        Write-Host "Error: $_" -ForegroundColor Red
        exit 1
    }
}
else {
    $downloadUrl = "https://github.com/$RepoOwner/$RepoName/releases/download/$Version/$BinaryName"
}

Write-Host "  Version: $Version" -ForegroundColor Gray

# 2. Download into skills/
if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}

$destPath = Join-Path $InstallDir $BinaryName
Write-Host "[2/2] Downloading to skills/ ..." -ForegroundColor Yellow

try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $webClient = New-Object System.Net.WebClient
    $webClient.Headers.Add("User-Agent", "DocReaderCli-Setup")
    $webClient.DownloadFile($downloadUrl, $destPath)
    $fileSize = (Get-Item $destPath).Length / 1MB
    Write-Host "  Done: $destPath ($([math]::Round($fileSize, 1)) MB)" -ForegroundColor Gray
}
catch {
    Write-Host "Error: Download failed. $_" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== Setup Complete ===" -ForegroundColor Green
Write-Host "  skills/$BinaryName ready." -ForegroundColor Cyan
