<#
.SYNOPSIS
    DocUnlockCli 셋업 - GitHub Release의 zip을 내려받아 SKILL.md 옆에 풉니다.

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
$ZipName = "DocUnlockCli-win-x64.zip"
$BinaryName = "DocUnlockCli.exe"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallDir = $ScriptDir
$ZipPath = Join-Path $InstallDir $ZipName
$BinaryPath = Join-Path $InstallDir $BinaryName

Write-Host "=== DocUnlockCli Setup ===" -ForegroundColor Cyan

Write-Host "  InstallDir: $InstallDir" -ForegroundColor Gray

if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}

$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($userPath -notlike "*$InstallDir*") {
    [Environment]::SetEnvironmentVariable("PATH", "$userPath;$InstallDir", "User")
    Write-Host "[1/3] PATH updated (restart terminal to apply)" -ForegroundColor Yellow
}
else {
    Write-Host "[1/3] PATH already contains InstallDir" -ForegroundColor Yellow
}

if (Test-Path $BinaryPath) {
    Write-Host "[2/3] Existing binary found, skipping release lookup, download, and extract." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "=== Setup Complete ===" -ForegroundColor Green
    Write-Host "  $BinaryName registered to PATH — run from anywhere" -ForegroundColor Cyan
    exit 0
}

if ($Version -eq "latest") {
    Write-Host "[2/3] Fetching latest release..." -ForegroundColor Yellow
    $releaseUrl = "https://api.github.com/repos/$RepoOwner/$RepoName/releases/tags/latest"
    try {
        $release = Invoke-RestMethod -Uri $releaseUrl -Headers @{ "User-Agent" = "DocUnlockCli-Setup" }
        $asset = $release.assets | Where-Object { $_.name -eq $ZipName } | Select-Object -First 1
        if (-not $asset) { throw "Release asset '$ZipName' not found." }
        $downloadUrl = $asset.browser_download_url
        $Version = $release.tag_name
    }
    catch {
        Write-Host "Error: $_" -ForegroundColor Red
        exit 1
    }
}
else {
    $downloadUrl = "https://github.com/$RepoOwner/$RepoName/releases/download/$Version/$ZipName"
}

Write-Host "  Version: $Version" -ForegroundColor Gray

Write-Host "[3/3] Downloading release zip..." -ForegroundColor Yellow

try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $webClient = New-Object System.Net.WebClient
    $webClient.Headers.Add("User-Agent", "DocUnlockCli-Setup")
    $webClient.DownloadFile($downloadUrl, $ZipPath)

    $fileSize = (Get-Item $ZipPath).Length / 1MB
    Write-Host "  Done: $ZipPath ($([math]::Round($fileSize, 1)) MB)" -ForegroundColor Gray
}
catch {
    Write-Host "Error: Download failed. $_" -ForegroundColor Red
    exit 1
}

Write-Host "  Extracting release zip..." -ForegroundColor Yellow

try {
    Expand-Archive -Path $ZipPath -DestinationPath $InstallDir -Force

    if (-not (Test-Path $BinaryPath)) {
        throw "Expected extracted binary not found: $BinaryPath"
    }

    Remove-Item $ZipPath -Force
}
catch {
    Write-Host "Error: Extract failed. $_" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== Setup Complete ===" -ForegroundColor Green
Write-Host "  $BinaryName registered to PATH — run from anywhere" -ForegroundColor Cyan
