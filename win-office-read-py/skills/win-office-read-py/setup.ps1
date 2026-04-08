<#
.SYNOPSIS
    Python 기반 DocReaderCli 셋업 - 로컬 venv 생성 후 pywin32/psutil을 설치합니다.

.EXAMPLE
    .\setup.ps1
    .\setup.ps1 -PythonExe py
#>

param(
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Resolve-Path (Join-Path $ScriptDir "..\..\DocReaderCliPy")
$VenvDir = Join-Path $ScriptDir ".venv"
$RequirementsPath = Join-Path $ProjectDir "requirements.txt"

Write-Host "=== DocReaderCli Python Setup ===" -ForegroundColor Cyan
Write-Host "  ProjectDir: $ProjectDir" -ForegroundColor Gray
Write-Host "  VenvDir: $VenvDir" -ForegroundColor Gray

if (-not (Test-Path $RequirementsPath)) {
    throw "requirements.txt not found: $RequirementsPath"
}

if (-not (Test-Path $VenvDir)) {
    Write-Host "[1/3] Creating virtual environment..." -ForegroundColor Yellow
    & $PythonExe -m venv $VenvDir
}
else {
    Write-Host "[1/3] Virtual environment already exists." -ForegroundColor Yellow
}

$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    throw "Virtual environment python not found: $VenvPython"
}

Write-Host "[2/3] Installing dependencies..." -ForegroundColor Yellow
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r $RequirementsPath

$PostInstall = Join-Path $VenvDir "Scripts\pywin32_postinstall.py"
Write-Host "[3/3] Finalizing pywin32 registration..." -ForegroundColor Yellow
if (Test-Path $PostInstall) {
    & $VenvPython $PostInstall -install
}
else {
    Write-Host "  pywin32_postinstall.py not found, skipping." -ForegroundColor DarkYellow
}

Write-Host ""
Write-Host "=== Setup Complete ===" -ForegroundColor Green
Write-Host "  Use .\DocReaderCli.cmd --file <path>" -ForegroundColor Cyan
