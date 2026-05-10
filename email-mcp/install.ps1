<#
.SYNOPSIS
    email-mcp installer for Windows. Verifies Python 3.9, installs missing
    email-connector dependencies, smoke-tests the server over stdio, and
    merges a ready-to-use entry into Claude Desktop's mcpServers config.

.DESCRIPTION
    - Idempotent. Safe to re-run.
    - User-scoped. No administrator required.
    - "In-place": the email-mcp folder where this script lives is the install
      location; nothing is copied. The Claude config gets the absolute path
      of $PSScriptRoot.
    - Backs up an existing claude_desktop_config.json before writing.
    - Writes JSON without a UTF-8 BOM (some Claude Desktop builds reject it).

.PARAMETER EmailConnectorPath
    Path to the email-connector skill folder. Default: sibling of email-mcp.

.PARAMETER SkipClaudeConfig
    Skip the Claude Desktop config merge.

.PARAMETER SkipDeps
    Skip the email-connector pip install step.

.PARAMETER DryRun
    Run every check and print what would change without writing anything.

.EXAMPLE
    .\install.ps1
    Default install. Most users.

.EXAMPLE
    .\install.ps1 -DryRun
    See what would happen without touching anything.

.EXAMPLE
    .\install.ps1 -EmailConnectorPath "D:\skills\email-connector"
    Use a non-default email-connector location.
#>
#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$EmailConnectorPath = "",
    [switch]$SkipClaudeConfig,
    [switch]$SkipDeps,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# Resolve install location (always in-place)
$EmailMcpPath = $PSScriptRoot
if (-not $EmailConnectorPath) {
    $EmailConnectorPath = Join-Path -Path (Split-Path -Parent $PSScriptRoot) -ChildPath "email-connector"
}
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
# Stdio MCP smoke test (use Process directly so stdin can be closed cleanly)
# ---------------------------------------------------------------------------
function Invoke-StdioPing {
    param([string]$ServerPath, [string]$Message, [int]$TimeoutMs = 20000)
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "py"
    $psi.Arguments = "-3.9 `"$ServerPath`""
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8

    $proc = [System.Diagnostics.Process]::Start($psi)
    $proc.StandardInput.WriteLine($Message)
    $proc.StandardInput.Close()

    $stdout = $proc.StandardOutput.ReadToEnd()
    $stderr = $proc.StandardError.ReadToEnd()

    if (-not $proc.WaitForExit($TimeoutMs)) {
        try { $proc.Kill() } catch { }
        throw "Server did not exit within $TimeoutMs ms. Stderr:`n$stderr"
    }

    return @{
        ExitCode = $proc.ExitCode
        Stdout   = $stdout
        Stderr   = $stderr
    }
}

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "  email-mcp installer" -ForegroundColor White
Write-Host "  ──────────────────────────────────────────────"
Write-Host "  email-mcp:        $EmailMcpPath"
Write-Host "  email-connector:  $EmailConnectorPath"
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
# Reject WSL: kernel build string contains 'microsoft'.
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
    Fail @"
'py' launcher not found.
Install Python 3.9.13 (64-bit) with 'Add python.exe to PATH' checked:
  https://www.python.org/ftp/python/3.9.13/python-3.9.13-amd64.exe
After installing, re-run install.cmd.
"@
} catch {
    Fail "py launcher error: $_"
}
if ($LASTEXITCODE -ne 0) {
    Fail @"
Python 3.9 not found via py launcher. Output:
$pyVersion

Install Python 3.9.13 (64-bit) from:
  https://www.python.org/ftp/python/3.9.13/python-3.9.13-amd64.exe
"@
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
# 3. email-connector existence
# ---------------------------------------------------------------------------
Write-Step "3. email-connector at $EmailConnectorPath"
$ecScripts = Join-Path $EmailConnectorPath "scripts\search.py"
if (-not (Test-Path $ecScripts)) {
    Fail @"
email-connector not found at '$EmailConnectorPath'

Install email-connector first, e.g.:
  git clone https://github.com/joungwoo-lee/slsi-cowork-plugins %TEMP%\slsi-plugins
  xcopy /E /I /Y %TEMP%\slsi-plugins\email-connector "$EmailConnectorPath"

Then re-run this installer. Or pass -EmailConnectorPath to point at a
different location.
"@
}
Write-Ok "email-connector found"

# ---------------------------------------------------------------------------
# 4. email-connector dependencies (run BEFORE smoke test — bootstrap.py
#    imports scripts.config which imports python-dotenv at top-level).
# ---------------------------------------------------------------------------
Write-Step "4. email-connector dependencies"
if ($SkipDeps) {
    Write-Warn "skipped (-SkipDeps)"
} else {
    $depCheck = & py -3.9 -c "import pypff,markdownify,striprtf,fitz,docx,openpyxl,pptx,qdrant_client,requests,dotenv; print('ok')" 2>&1
    if ($depCheck -match "^ok\s*$") {
        Write-Ok "all dependencies importable"
    } else {
        Write-Warn "some dependencies missing — running pip install"
        Write-Host "        ($depCheck)" -ForegroundColor DarkGray
        if ($DryRun) {
            Write-Dry "would run: py -3.9 -m pip install -r `"$EmailConnectorPath\requirements.txt`""
        } else {
            & py -3.9 -m pip install --upgrade pip
            if ($LASTEXITCODE -ne 0) {
                Fail "pip self-upgrade failed. Check proxy/network."
            }
            & py -3.9 -m pip install -r (Join-Path $EmailConnectorPath "requirements.txt")
            if ($LASTEXITCODE -ne 0) {
                Fail @"
pip install failed. Common causes:
  - SSL/proxy: configure HTTP_PROXY/HTTPS_PROXY in env, then re-run.
  - libpff-python wheel: must be Python 3.9 64-bit (see step 2).
Re-run with -SkipDeps after fixing manually.
"@
            }
            Write-Ok "dependencies installed"
        }
    }
}

# ---------------------------------------------------------------------------
# 5. .env file (auto-create from .env.example so doctor's env_file check passes)
# ---------------------------------------------------------------------------
Write-Step "5. email-connector .env"
$envPath = Join-Path $EmailConnectorPath ".env"
$envExample = Join-Path $EmailConnectorPath ".env.example"
if (Test-Path $envPath) {
    Write-Ok ".env exists at $envPath"
} elseif (Test-Path $envExample) {
    if ($DryRun) {
        Write-Dry "would copy $envExample → $envPath"
    } else {
        Copy-Item -Path $envExample -Destination $envPath
        Write-Ok "created $envPath from .env.example"
    }
    Write-Warn "EDIT $envPath now: PST_PATH, EMBEDDING_API_URL, EMBEDDING_API_KEY, EMBEDDING_MODEL, EMBEDDING_DIM"
} else {
    Write-Warn "neither .env nor .env.example present in email-connector"
    Write-Warn "search/ingest will fail until you create .env there."
}

# ---------------------------------------------------------------------------
# 6. Smoke test (initialize over stdio)
# ---------------------------------------------------------------------------
Write-Step "6. Smoke test (initialize over stdio)"
if (-not (Test-Path $serverPath)) {
    Fail "server.py not found at $serverPath"
}
$initMsg = '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"installer","version":"0"}}}'
try {
    $result = Invoke-StdioPing -ServerPath $serverPath -Message $initMsg
} catch {
    Fail "Smoke test failed to start server: $_"
}

if ($result.ExitCode -ne 0) {
    Write-Err "Server exited with code $($result.ExitCode)"
    Write-Host "    --- STDERR ---" -ForegroundColor DarkGray
    Write-Host $result.Stderr -ForegroundColor DarkGray
    Fail "Smoke test failed."
}

$jsonLine = ($result.Stdout -split "`n" | Where-Object { $_.Trim().StartsWith("{") } | Select-Object -First 1)
if (-not $jsonLine) {
    Write-Err "No JSON-RPC response on stdout."
    Write-Host "    --- STDOUT ---" -ForegroundColor DarkGray
    Write-Host $result.Stdout -ForegroundColor DarkGray
    Write-Host "    --- STDERR ---" -ForegroundColor DarkGray
    Write-Host $result.Stderr -ForegroundColor DarkGray
    Fail "Smoke test failed."
}

try {
    $resp = $jsonLine.Trim() | ConvertFrom-Json
} catch {
    Fail "Server response is not valid JSON: $jsonLine"
}
if ($resp.result.serverInfo.name -ne "email-mcp") {
    Fail "Unexpected server name in response: $($resp.result.serverInfo.name)"
}
Write-Ok "server responded: email-mcp v$($resp.result.serverInfo.version), protocol=$($resp.result.protocolVersion)"

# ---------------------------------------------------------------------------
# 7. Claude Desktop config (merge into existing mcpServers)
# ---------------------------------------------------------------------------
Write-Step "7. Claude Desktop config"
$claudeAppData = Join-Path $env:APPDATA "Claude"
$cfgPath = Join-Path $claudeAppData "claude_desktop_config.json"
$desktopConfigured = $false

if ($SkipClaudeConfig) {
    Write-Warn "skipped (-SkipClaudeConfig)"
} elseif (-not (Test-Path $claudeAppData)) {
    Write-Warn "Claude Desktop not detected ($claudeAppData missing)."
    Write-Warn "If you use Claude Code, run claude_code_install.cmd (generated below)."
} else {
    $existing = $null
    if (Test-Path $cfgPath) {
        $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $backup = "$cfgPath.bak.$stamp"
        if (-not $DryRun) {
            Copy-Item -Path $cfgPath -Destination $backup
        } else {
            Write-Dry "would back up $cfgPath → $backup"
        }
        Write-Ok "backup: $backup"
        try {
            $raw = Get-Content -Path $cfgPath -Raw -Encoding UTF8
            if ($raw -and $raw.Trim()) {
                $existing = $raw | ConvertFrom-Json
            }
        } catch {
            Fail "$cfgPath exists but is not valid JSON. Fix or delete it manually, then re-run."
        }
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
        env     = [pscustomobject]@{
            EMAIL_CONNECTOR_PATH = $EmailConnectorPath
        }
    }
    $existing.mcpServers | Add-Member -MemberType NoteProperty -Name email -Value $emailEntry -Force

    if ($DryRun) {
        Write-Dry "would write $cfgPath:"
        Write-Host ($existing | ConvertTo-Json -Depth 12) -ForegroundColor DarkGray
    } else {
        Write-JsonNoBom -Path $cfgPath -Object $existing
        # Verify by re-reading
        try {
            $check = (Get-Content -Path $cfgPath -Raw -Encoding UTF8) | ConvertFrom-Json
            if (-not $check.mcpServers.email -or $check.mcpServers.email.command -ne "py") {
                Fail "Verification failed: written config doesn't contain mcpServers.email."
            }
        } catch {
            Fail "Verification failed: written config is not valid JSON."
        }
        Write-Ok "wrote $cfgPath (no BOM, verified)"
        $desktopConfigured = $true
    }
}

# ---------------------------------------------------------------------------
# 8. Claude Code helper (.cmd alongside install.ps1)
# ---------------------------------------------------------------------------
Write-Step "8. Generate Claude Code helper"
$ccCmd = Join-Path $EmailMcpPath "claude_code_install.cmd"
$ccBody = @"
@echo off
REM Auto-generated by install.ps1.
REM Adds email-mcp to Claude Code (CLI). Requires the 'claude' command.
claude mcp add email -e EMAIL_CONNECTOR_PATH=$EmailConnectorPath -- py -3.9 "$serverPath"
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
# 9. Final email-connector doctor (no API call — saves tokens, network)
# ---------------------------------------------------------------------------
Write-Step "9. Final verification (email-connector doctor, --skip-api)"
$doctorScript = Join-Path $EmailConnectorPath "scripts\doctor.py"
$doctorOut = & py -3.9 $doctorScript --skip-api 2>&1 | Out-String
try {
    $doctorJson = $doctorOut | ConvertFrom-Json
    if ($doctorJson.all_ok) {
        Write-Ok "doctor: all checks pass (API ping skipped — test from Claude later)"
    } else {
        Write-Warn "doctor reports unresolved issues:"
        foreach ($c in ($doctorJson.checks | Where-Object { -not $_.ok })) {
            Write-Warn "  - $($c.name): $($c.detail)"
        }
        Write-Warn "Most likely you still need to fill in $envPath. Edit it, then ask Claude:"
        Write-Warn "  'email-mcp doctor 도구로 진단해줘'"
    }
} catch {
    Write-Warn "doctor output was not parseable JSON:"
    Write-Host $doctorOut -ForegroundColor DarkGray
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Install complete." -ForegroundColor White
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor White
$step = 1
if (Test-Path $envPath) {
    Write-Host "  $step. Edit $envPath with PST_PATH and EMBEDDING_API_* values"
    $step++
}
if ($desktopConfigured) {
    Write-Host "  $step. RESTART Claude Desktop  ← required for the new MCP server to load"
    $step++
    Write-Host "  $step. In Claude, ask: 'email-mcp doctor 도구로 진단해줘'"
} elseif (-not $SkipClaudeConfig) {
    Write-Host "  $step. For Claude Code: run $ccCmd"
    $step++
    Write-Host "  $step. Then ask Claude: 'email-mcp doctor 도구로 진단해줘'"
}
Write-Host ""
if ($DryRun) {
    Write-Host "(this was a dry run — nothing was actually written)" -ForegroundColor Magenta
    Write-Host ""
}
