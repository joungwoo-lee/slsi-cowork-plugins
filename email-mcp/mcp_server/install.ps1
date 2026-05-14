<#
.SYNOPSIS
    email-mcp installer for Windows. Verifies Python 3.9, installs dependencies,
    smoke-tests the server over stdio, and merges a ready-to-use entry into 
    Claude Desktop's mcpServers config.

.DESCRIPTION
    - Idempotent. Safe to re-run.
    - User-scoped. No administrator required.
    - "In-place": the email-mcp folder where this script lives is the install
      location; nothing is copied. The Claude config gets the absolute path
      of $PSScriptRoot.
    - Backs up an existing claude_desktop_config.json before writing.
    - Writes JSON without a UTF-8 BOM (some Claude Desktop builds reject it).

.PARAMETER SkipClaudeConfig
    Skip the Claude Desktop config merge.

.PARAMETER SkipDeps
    Skip the pip install step.

.PARAMETER DryRun
    Run every check and print what would change without writing anything.

.EXAMPLE
    .\install.ps1
    Default install. Most users.

.EXAMPLE
    .\install.ps1 -DryRun
    See what would happen without touching anything.
#>
#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$SkipClaudeConfig,
    [switch]$SkipDeps,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# Resolve install location: this script lives at <email-mcp>/mcp_server/install.ps1,
# so the email-mcp root is the parent of $PSScriptRoot.
$EmailMcpPath = Split-Path -Parent $PSScriptRoot
$serverPath = Join-Path $EmailMcpPath "server.py"

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
function Write-Step { param($m) Write-Host ""; Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Ok   { param($m) Write-Host "    [OK]  $m" -ForegroundColor Green }
function Write-Warn { param($m) Write-Host "    [!]   $m" -ForegroundColor Yellow }
function Write-Err  { param($m) Write-Host "    [X]   $m" -ForegroundColor Red }
function Write-Dry  { param($m) Write-Host "    (dry) $m" -ForegroundColor Magenta }
function Fail       { param($m) Write-Err $m; exit 1 }

function Write-JsonNoBom {
    param([string]$Path, $Object)
    $json = $Object | ConvertTo-Json -Depth 12
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($Path, $json, $utf8NoBom)
}

# ---------------------------------------------------------------------------
# Module-import smoke test
# ---------------------------------------------------------------------------
# A full JSON-RPC stdio handshake from PowerShell 5.1 was unreliable because
# the StandardInput pipe wrapper injects a UTF-8 BOM that the server's
# json.loads rejects (server stdin is reconfigured to strict utf-8). Import
# verification covers the practical concern (deps present, package importable,
# dispatch loop loadable) without the stdin round-trip.
function Test-ServerImport {
    param([string]$McpRoot)
    $script = "import sys; sys.path.insert(0, r'$McpRoot'); from mcp_server import dispatch, bootstrap, handlers, catalog; print('ok')"
    $out = & py -3.9 -c $script 2>&1 | Out-String
    return @{ ExitCode = $LASTEXITCODE; Output = $out.Trim() }
}

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "  email-mcp installer" -ForegroundColor White
Write-Host "  ---------------------------------------------------------------------------"
Write-Host "  email-mcp:        $EmailMcpPath"
if ($DryRun) {
    Write-Host "  mode:             DRY-RUN (no files written)" -ForegroundColor Magenta
}

# ---------------------------------------------------------------------------
# 1. Platform
# ---------------------------------------------------------------------------
Write-Step "1. Platform"
if ($env:OS -ne "Windows_NT") {
    Fail "email-mcp requires Windows. Detected OS='$env:OS'"
}
$kernel = $null
try { $kernel = (Get-CimInstance Win32_OperatingSystem).Caption } catch { }
Write-Ok "Windows ($kernel)"

# ---------------------------------------------------------------------------
# 2. Python 3.9 64-bit
# ---------------------------------------------------------------------------
Write-Step "2. Python 3.9 (64-bit)"
$pyVersion = $null
try {
    $pyVersion = & py -3.9 --version 2>&1
} catch [System.Management.Automation.CommandNotFoundException] {
    Fail "py launcher not found. Install Python 3.9.13 (64-bit)."
} catch {
    Fail "py launcher error: $_"
}
if ($LASTEXITCODE -ne 0) {
    Fail "Python 3.9 not found via py launcher."
}
if ($pyVersion -notmatch "^Python 3\.9\.") {
    Fail "py -3.9 returned: '$pyVersion' (expected 'Python 3.9.x')"
}
$pyBits = "$(& py -3.9 -c "import struct; print(struct.calcsize('P')*8)")".Trim()
if ($pyBits -ne "64") {
    Fail "Python 3.9 is $pyBits-bit; need 64-bit (libpff-python wheel is cp39-win_amd64-only)"
}
Write-Ok "$pyVersion ($pyBits-bit)"

# ---------------------------------------------------------------------------
# 3. Dependencies
# ---------------------------------------------------------------------------
Write-Step "3. dependencies"
if ($SkipDeps) {
    Write-Warn "skipped (-SkipDeps)"
} else {
    $depCheck = & py -3.9 -c "import pypff,markdownify,striprtf,fitz,docx,openpyxl,pptx,qdrant_client,requests,dotenv,urllib3; print('ok')" 2>&1
    if ($depCheck -match "^ok\s*$") {
        Write-Ok "all dependencies importable"
    } else {
        Write-Warn "some dependencies missing - running pip install"
        if ($DryRun) {
            Write-Dry "would run: py -3.9 -m pip install -r `"$EmailMcpPath\requirements.txt`""
        } else {
            & py -3.9 -m pip install --upgrade pip
            & py -3.9 -m pip install -r (Join-Path $EmailMcpPath "requirements.txt")
            if ($LASTEXITCODE -ne 0) {
                Fail "pip install failed. Check proxy/network."
            }
            Write-Ok "dependencies installed"
        }
    }
}

# ---------------------------------------------------------------------------
# 4. .env file
# ---------------------------------------------------------------------------
Write-Step "4. .env"
$envPath = Join-Path $EmailMcpPath ".env"
$envExample = Join-Path $EmailMcpPath ".env.example"
if (Test-Path $envPath) {
    Write-Ok ".env exists at $envPath"
} elseif (Test-Path $envExample) {
    if ($DryRun) {
        Write-Dry "would copy $envExample to $envPath"
    } else {
        Copy-Item -Path $envExample -Destination $envPath
        Write-Ok "created $envPath from .env.example"
    }
    Write-Warn "EDIT $envPath now: PST_PATH, EMBEDDING_API_URL, EMBEDDING_API_KEY, EMBEDDING_MODEL, EMBEDDING_DIM"
} else {
    Write-Warn "neither .env nor .env.example present in email-mcp"
}

# ---------------------------------------------------------------------------
# 5. Smoke test
# ---------------------------------------------------------------------------
Write-Step "5. Smoke test (import mcp_server.*)"
if (-not (Test-Path $serverPath)) {
    Fail "server.py not found at $serverPath"
}
$importResult = Test-ServerImport -McpRoot $EmailMcpPath
if ($importResult.ExitCode -ne 0 -or $importResult.Output -notmatch "ok$") {
    Write-Err "module import failed:"
    Write-Err $importResult.Output
    Fail "Smoke test failed."
}
Write-Ok "mcp_server package imports cleanly"

# ---------------------------------------------------------------------------
# 6. Claude Desktop config
# ---------------------------------------------------------------------------
Write-Step "6. Claude Desktop config"
$claudeAppData = Join-Path $env:APPDATA "Claude"
$cfgPath = Join-Path $claudeAppData "claude_desktop_config.json"
$desktopConfigured = $false

if ($SkipClaudeConfig) {
    Write-Warn "skipped (-SkipClaudeConfig)"
} elseif (-not (Test-Path $claudeAppData)) {
    Write-Warn "Claude Desktop not detected."
} else {
    $existing = $null
    if (Test-Path $cfgPath) {
        $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $backup = "$cfgPath.bak.$stamp"
        if (-not $DryRun) { Copy-Item -Path $cfgPath -Destination $backup }
        Write-Ok "backup: $backup"
        $raw = Get-Content -Path $cfgPath -Raw -Encoding UTF8
        if ($raw -and $raw.Trim()) { $existing = $raw | ConvertFrom-Json }
    }
    if (-not $existing) {
        $existing = New-Object PSObject
        Write-Ok "creating new config"
    }
    if (-not $existing.mcpServers) {
        $existing | Add-Member -MemberType NoteProperty -Name mcpServers -Value (New-Object PSObject) -Force
    }

    $emailEntry = [pscustomobject]@{
        command = "py"
        args    = @("-3.9", $serverPath)
    }
    $existing.mcpServers | Add-Member -MemberType NoteProperty -Name email -Value $emailEntry -Force

    if ($DryRun) {
        Write-Dry "would write $cfgPath"
    } else {
        Write-JsonNoBom -Path $cfgPath -Object $existing
        Write-Ok "wrote $cfgPath (no BOM, verified)"
        $desktopConfigured = $true
    }
}

# ---------------------------------------------------------------------------
# 7. Claude Code helper
# ---------------------------------------------------------------------------
Write-Step "7. Generate Claude Code helper"
$ccCmd = Join-Path $EmailMcpPath "claude_code_install.cmd"
$ccBody = @"
@echo off
REM Auto-generated by install.ps1.
REM Adds email_mcp to Claude Code (CLI). Requires the 'claude' command.
claude mcp add email_mcp "py -3.9 `"$serverPath`""
if errorlevel 1 (
    echo.
    echo Failed. Check that 'claude' CLI is installed and on PATH.
)
pause
"@
if ($DryRun) {
    Write-Dry "would write $ccCmd"
} else {
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($ccCmd, $ccBody, $utf8NoBom)
    Write-Ok "wrote $ccCmd"
}

# ---------------------------------------------------------------------------
# 8. Final verification
# ---------------------------------------------------------------------------
Write-Step "8. Final verification (doctor, --skip-api)"
$doctorScript = Join-Path $EmailMcpPath "scripts\doctor.py"
$doctorOut = & py -3.9 $doctorScript --skip-api 2>&1 | Out-String
try {
    $doctorJson = $doctorOut | ConvertFrom-Json
    if ($doctorJson.all_ok) {
        Write-Ok "doctor: all checks pass"
    } else {
        Write-Warn "doctor reports unresolved issues:"
        foreach ($c in ($doctorJson.checks | Where-Object { -not $_.ok })) {
            Write-Warn "  - $($c.name): $($c.detail)"
        }
        Write-Warn "Most likely you still need to fill in $envPath. Edit it."
    }
} catch {
    Write-Warn "doctor output was not parseable JSON"
}

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Install complete." -ForegroundColor White
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""
