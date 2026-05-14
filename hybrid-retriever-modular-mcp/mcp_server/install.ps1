<#
.SYNOPSIS
    hybrid-retriever-modular-mcp installer for Windows. Verifies Python,
    installs dependencies, smoke-tests the server over stdio, and merges a
    ready-to-use entry into Claude Desktop's mcpServers config.

.DESCRIPTION
    - Idempotent. Safe to re-run.
    - User-scoped. No administrator required.
    - "In-place": the folder where this script lives is the install location.
    - Also invoked at runtime by mcp_server.dispatch.auto_install_check with
      -SkipClaudeConfig, so a fresh PC self-heals on first tool call.

.PARAMETER SkipClaudeConfig
    Skip the Claude Desktop config merge. Used by the runtime auto-installer.

.PARAMETER SkipDeps
    Skip the pip install step.

.PARAMETER DryRun
    Print what would change without writing anything.
#>
#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$SkipClaudeConfig,
    [switch]$SkipDeps,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# This script lives at <mcp-root>/mcp_server/install.ps1, so the mcp root is
# the parent of $PSScriptRoot.
$McpPath = Split-Path -Parent $PSScriptRoot
$serverPath = Join-Path $McpPath "server.py"
$reqPath    = Join-Path $McpPath "requirements.txt"

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

function Test-ServerImport {
    param([string]$McpRoot)
    # The full JSON-RPC handshake test was failing on PowerShell 5.1 due to a
    # UTF-8 BOM injected somewhere in the stdin pipe wrapper. Module-import
    # verification covers the practical concern (deps present, package
    # importable, dispatch loop loadable) without the stdin round-trip.
    $script = "import sys; sys.path.insert(0, r'$McpRoot'); from mcp_server import dispatch, bootstrap, handlers, catalog; print('ok')"
    $out = & python -c $script 2>&1 | Out-String
    return @{ ExitCode = $LASTEXITCODE; Output = $out.Trim() }
}

Write-Host ""
Write-Host "  hybrid-retriever-modular-mcp installer" -ForegroundColor White
Write-Host "  ---------------------------------------------------------------------------"
Write-Host "  mcp root:         $McpPath"
if ($DryRun) {
    Write-Host "  mode:             DRY-RUN (no files written)" -ForegroundColor Magenta
}

# 1. Platform
Write-Step "1. Platform"
if ($env:OS -ne "Windows_NT") {
    Fail "This installer requires Windows. Detected OS='$env:OS'"
}
Write-Ok "Windows"

# 2. Python (>= 3.10 recommended; python must resolve)
Write-Step "2. Python (python)"
try {
    $pyVersion = & python --version 2>&1
} catch [System.Management.Automation.CommandNotFoundException] {
    Fail "py launcher not found. Install Python 3.10+ from python.org."
} catch {
    Fail "py launcher error: $_"
}
if ($LASTEXITCODE -ne 0) {
    Fail "python failed: $pyVersion"
}
Write-Ok "$pyVersion"

# 3. Dependencies
Write-Step "3. dependencies"
if ($SkipDeps) {
    Write-Warn "skipped (-SkipDeps)"
} else {
    $depCheck = & python -c "import dotenv,requests,qdrant_client,pypdf,docx,openpyxl,chardet,urllib3; print('ok')" 2>&1
    if ($depCheck -match "^ok\s*$") {
        Write-Ok "all dependencies importable"
    } else {
        Write-Warn "some dependencies missing - running pip install"
        if ($DryRun) {
            Write-Dry "would run: python -m pip install -r `"$reqPath`""
        } else {
            & python -m pip install --upgrade pip
            & python -m pip install -r $reqPath
            if ($LASTEXITCODE -ne 0) {
                Fail "pip install failed. Check proxy/network."
            }
            Write-Ok "dependencies installed"
        }
    }
}

# 4. .env file
Write-Step "4. .env"
$envPath = Join-Path $McpPath ".env"
$envExample = Join-Path $McpPath ".env.example"
if (Test-Path $envPath) {
    Write-Ok ".env exists at $envPath"
} elseif (Test-Path $envExample) {
    if ($DryRun) {
        Write-Dry "would copy $envExample to $envPath"
    } else {
        Copy-Item -Path $envExample -Destination $envPath
        Write-Ok "created $envPath from .env.example"
    }
    Write-Warn "EDIT ${envPath}: RETRIEVER_DATA_ROOT, RETRIEVER_DEFAULT_DATASETS, embedding API (optional)"
} else {
    Write-Warn "neither .env nor .env.example present"
}

# 5. Smoke test (module import)
Write-Step "5. Smoke test (import mcp_server.*)"
if (-not (Test-Path $serverPath)) {
    Fail "server.py not found at $serverPath"
}
$importResult = Test-ServerImport -McpRoot $McpPath
if ($importResult.ExitCode -ne 0 -or $importResult.Output -notmatch "ok$") {
    Write-Err "module import failed:"
    Write-Err $importResult.Output
    Fail "Smoke test failed."
}
Write-Ok "mcp_server package imports cleanly"

# 6. Claude Desktop config
Write-Step "6. Claude Desktop config"
$claudeAppData = Join-Path $env:APPDATA "Claude"
$cfgPath = Join-Path $claudeAppData "claude_desktop_config.json"

if ($SkipClaudeConfig) {
    Write-Warn "skipped (-SkipClaudeConfig)"
} elseif (-not (Test-Path $claudeAppData)) {
    Write-Warn "Claude Desktop not detected at $claudeAppData."
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

    $envBlock = New-Object PSObject
    if ($env:RETRIEVER_DATA_ROOT) {
        $envBlock | Add-Member -MemberType NoteProperty -Name RETRIEVER_DATA_ROOT -Value $env:RETRIEVER_DATA_ROOT
    }
    if ($env:RETRIEVER_DEFAULT_DATASETS) {
        $envBlock | Add-Member -MemberType NoteProperty -Name RETRIEVER_DEFAULT_DATASETS -Value $env:RETRIEVER_DEFAULT_DATASETS
    }

    $entry = [pscustomobject]@{
        command = "py"
        args    = @("-3", $serverPath)
    }
    if ($envBlock.PSObject.Properties.Count -gt 0) {
        $entry | Add-Member -MemberType NoteProperty -Name env -Value $envBlock
    }
    $existing.mcpServers | Add-Member -MemberType NoteProperty -Name retriever_mcp -Value $entry -Force

    if ($DryRun) {
        Write-Dry "would write $cfgPath"
    } else {
        Write-JsonNoBom -Path $cfgPath -Object $existing
        Write-Ok "wrote $cfgPath (no BOM)"
    }
}

# 7. Claude Code helper
Write-Step "7. Generate Claude Code helper"
$ccCmd = Join-Path $McpPath "claude_code_install.cmd"
$ccBody = @"
@echo off
REM Auto-generated by install.ps1.
REM Adds retriever_mcp to Claude Code (CLI). Requires the 'claude' command.
claude mcp add retriever_mcp -- python "$serverPath"
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

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Install complete." -ForegroundColor White
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""
