<#
.SYNOPSIS
    One-click installer for mcp-server-excel (Windows PowerShell 5.1+)
.DESCRIPTION
    1. Check Windows environment
    2. Detect the latest GitHub release
    3. Download and extract MCP Server zip and optional CLI zip
    4. Find mcp-excel.exe and add it to PATH
    5. Write plugin .mcp.json
    6. Register the MCP server in Claude Code, Claude Desktop, and VS Code settings
    7. Run a stdio handshake test
.NOTES
    Run: powershell -ExecutionPolicy Bypass -File setup_excel_mcp.ps1
#>

$ErrorActionPreference = "Stop"
$script:CurrentStage = "Init"
$script:CurrentAction = "Before start"

$GH_REPO = "sbroenne/mcp-server-excel"
$GH_API = "https://api.github.com/repos/$GH_REPO/releases/latest"
$INSTALL_DIR = Join-Path $env:USERPROFILE "ExcelMcp"
$EXE_NAME = "mcp-excel.exe"
$CLI_NAME = "excelcli.exe"

function Log($msg) {
    Write-Host ">>> $msg"
}

function Ok($msg) {
    Write-Host "[OK] $msg" -ForegroundColor Green
}

function Warn($msg) {
    Write-Host "[WARN] $msg" -ForegroundColor Yellow
}

function Fail($msg) {
    Write-Host "[FAIL] Stage: $script:CurrentStage" -ForegroundColor Red
    Write-Host "[FAIL] Action: $script:CurrentAction" -ForegroundColor Red
    Write-Host "[FAIL] $msg" -ForegroundColor Red
    exit 1
}

function StartStep($msg) {
    $script:CurrentStage = $msg
    $script:CurrentAction = "Idle"
    Write-Host ""
    Write-Host "=== $msg ===" -ForegroundColor Cyan
}

function StartAction($msg) {
    $script:CurrentAction = $msg
    Write-Host " -> $msg"
}

function DownloadReleaseFile($url, $destinationPath, $userAgent) {
    $webClient = New-Object System.Net.WebClient
    $webClient.Headers.Add("User-Agent", $userAgent)
    try {
        $webClient.DownloadFile($url, $destinationPath)
    } finally {
        $webClient.Dispose()
    }
}

function RemoveJsonComments($text) {
    if ([string]::IsNullOrEmpty($text)) {
        return $text
    }

    $sb = New-Object System.Text.StringBuilder
    $inString = $false
    $escapeNext = $false
    $inLineComment = $false
    $inBlockComment = $false

    for ($i = 0; $i -lt $text.Length; $i++) {
        $char = $text[$i]
        if ($i + 1 -lt $text.Length) {
            $next = $text[$i + 1]
        } else {
            $next = [char]0
        }

        if ($inLineComment) {
            if ($char -eq "`r" -or $char -eq "`n") {
                $inLineComment = $false
                [void]$sb.Append($char)
            }
            continue
        }

        if ($inBlockComment) {
            if ($char -eq '*' -and $next -eq '/') {
                $inBlockComment = $false
                $i++
            }
            continue
        }

        if ($inString) {
            [void]$sb.Append($char)
            if ($escapeNext) {
                $escapeNext = $false
            } elseif ($char -eq '\\') {
                $escapeNext = $true
            } elseif ($char -eq '"') {
                $inString = $false
            }
            continue
        }

        if ($char -eq '/' -and $next -eq '/') {
            $inLineComment = $true
            $i++
            continue
        }

        if ($char -eq '/' -and $next -eq '*') {
            $inBlockComment = $true
            $i++
            continue
        }

        [void]$sb.Append($char)
        if ($char -eq '"') {
            $inString = $true
        }
    }

    return $sb.ToString()
}

try {
    StartStep "1. Check Windows"
    StartAction "Verify operating system"
    if ($env:OS -ne "Windows_NT") {
        Fail "This script only runs on Windows."
    }

    StartStep "2. Resolve release"
    StartAction "Call GitHub API"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $release = Invoke-RestMethod -Uri $GH_API -Headers @{ "User-Agent" = "excel-mcp-setup" }

    $version = $release.tag_name
    Log "Latest version: $version"

    $mcpAsset = $release.assets | Where-Object { $_.name -like "ExcelMcp-MCP-Server-*-windows.zip" } | Select-Object -First 1
    $cliAsset = $release.assets | Where-Object { $_.name -like "ExcelMcp-CLI-*-windows.zip" } | Select-Object -First 1

    if (-not $mcpAsset) {
        Fail "Could not find the MCP Server zip asset. See https://github.com/$GH_REPO/releases/latest"
    }

    $mcpUrl = $mcpAsset.browser_download_url
    if ($cliAsset) {
        $cliUrl = $cliAsset.browser_download_url
    } else {
        $cliUrl = $null
    }

    Log "MCP Server asset: $($mcpAsset.name)"
    if ($cliUrl) {
        Log "CLI asset: $($cliAsset.name)"
    }

    StartStep "3. Download and install"
    if (Test-Path $INSTALL_DIR) {
        StartAction "Remove previous install directory"
        Log "Cleaning existing directory: $INSTALL_DIR"
        Remove-Item $INSTALL_DIR -Recurse -Force
    }

    StartAction "Create install and temp directories"
    New-Item -ItemType Directory -Path $INSTALL_DIR -Force | Out-Null
    $tempDir = Join-Path $env:TEMP "excel-mcp-setup-$(Get-Random)"
    New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

    try {
        $mcpZip = Join-Path $tempDir "mcp-server.zip"
        StartAction "Download MCP Server zip"
        Log "Downloading MCP Server from $mcpUrl"
        DownloadReleaseFile $mcpUrl $mcpZip "excel-mcp-setup"
        $mcpZipSize = (Get-Item $mcpZip).Length / 1MB
        Log "Downloaded: $mcpZip ($([math]::Round($mcpZipSize, 1)) MB)"

        $extractDir = Join-Path $tempDir "extracted-mcp"
        StartAction "Extract MCP Server zip"
        Expand-Archive -Path $mcpZip -DestinationPath $extractDir -Force

        StartAction "Find mcp-excel.exe"
        $foundExe = Get-ChildItem -Path $extractDir -Filter $EXE_NAME -Recurse | Select-Object -First 1
        if (-not $foundExe) {
            Fail "Could not find $EXE_NAME inside the extracted MCP Server zip. Extract path: $extractDir"
        }

        $exeSourceDir = $foundExe.DirectoryName
        StartAction "Copy MCP Server files"
        Copy-Item -Path "$exeSourceDir\*" -Destination $INSTALL_DIR -Recurse -Force
        Ok "MCP Server installed"

        if ($cliUrl) {
            $cliZip = Join-Path $tempDir "cli.zip"
            StartAction "Download CLI zip"
            Log "Downloading CLI from $cliUrl"
            DownloadReleaseFile $cliUrl $cliZip "excel-mcp-setup"
            $cliZipSize = (Get-Item $cliZip).Length / 1MB
            Log "Downloaded: $cliZip ($([math]::Round($cliZipSize, 1)) MB)"

            $extractCliDir = Join-Path $tempDir "extracted-cli"
            StartAction "Extract CLI zip"
            Expand-Archive -Path $cliZip -DestinationPath $extractCliDir -Force

            StartAction "Find excelcli.exe"
            $foundCli = Get-ChildItem -Path $extractCliDir -Filter $CLI_NAME -Recurse | Select-Object -First 1
            if ($foundCli) {
                StartAction "Copy CLI files"
                Copy-Item -Path "$($foundCli.DirectoryName)\*" -Destination $INSTALL_DIR -Recurse -Force
                Ok "CLI installed"
            } else {
                Warn "Could not find $CLI_NAME inside the CLI zip. Skipping CLI install."
            }
        }
    } finally {
        StartAction "Clean temp directory"
        Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    }

    $mcpExePath = Join-Path $INSTALL_DIR $EXE_NAME
    $cliExePath = Join-Path $INSTALL_DIR $CLI_NAME

    if (-not (Test-Path $mcpExePath)) {
        Fail "$EXE_NAME was not installed to $mcpExePath"
    }
    Log "Installed executable: $mcpExePath"

    StartStep "4. Update PATH"
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($userPath -notlike "*$INSTALL_DIR*") {
        StartAction "Append install directory to user PATH"
        [Environment]::SetEnvironmentVariable("Path", "$userPath;$INSTALL_DIR", "User")
        $env:Path = "$env:Path;$INSTALL_DIR"
        Ok "PATH updated for current session and future sessions"
    } else {
        StartAction "Check existing PATH registration"
        Log "Install directory is already present in PATH"
    }

    StartStep "5. Write plugin .mcp.json"
    StartAction "Resolve plugin root"
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $pluginRoot = (Resolve-Path (Join-Path $scriptDir "..\..\..")).Path
    $mcpJsonPath = Join-Path $pluginRoot ".mcp.json"
    $escapedMcpExePath = $mcpExePath.Replace('\','\\')
    $mcpJsonContent = @"
{
  "mcpServers": {
    "excel-mcp": {
      "command": "$escapedMcpExePath",
      "args": [],
      "env": {}
    }
  }
}
"@
    StartAction "Write .mcp.json"
    Set-Content -Path $mcpJsonPath -Value $mcpJsonContent -Encoding UTF8
    Ok "Wrote .mcp.json: $mcpJsonPath"

    StartStep "6. Update client settings"
    $registeredTargets = @()

    $claudeSettings = Join-Path $env:USERPROFILE ".claude\settings.json"
    if (Test-Path $claudeSettings) {
        try {
            StartAction "Update Claude Code settings"
            $settings = Get-Content $claudeSettings -Raw -Encoding UTF8 | ConvertFrom-Json
            if (-not $settings.PSObject.Properties["mcpServers"]) {
                $settings | Add-Member -NotePropertyName "mcpServers" -NotePropertyValue ([PSCustomObject]@{})
            }
            $settings.mcpServers | Add-Member -NotePropertyName "excel-mcp" -NotePropertyValue ([PSCustomObject]@{
                command = $mcpExePath
                args = @()
                env = [PSCustomObject]@{}
            }) -Force
            $settings | ConvertTo-Json -Depth 10 | Set-Content $claudeSettings -Encoding UTF8
            $registeredTargets += "Claude Code"
        } catch {
            Warn "Failed to update Claude Code settings.json: $_"
        }
    }

    $claudeDesktop = Join-Path $env:APPDATA "Claude\claude_desktop_config.json"
    if (Test-Path $claudeDesktop) {
        try {
            StartAction "Update Claude Desktop settings"
            $cdConfig = Get-Content $claudeDesktop -Raw -Encoding UTF8 | ConvertFrom-Json
            if (-not $cdConfig.PSObject.Properties["mcpServers"]) {
                $cdConfig | Add-Member -NotePropertyName "mcpServers" -NotePropertyValue ([PSCustomObject]@{})
            }
            $cdConfig.mcpServers | Add-Member -NotePropertyName "excel-mcp" -NotePropertyValue ([PSCustomObject]@{
                command = "mcp-excel"
                args = @()
                env = [PSCustomObject]@{}
            }) -Force
            $cdConfig | ConvertTo-Json -Depth 10 | Set-Content $claudeDesktop -Encoding UTF8
            $registeredTargets += "Claude Desktop"
        } catch {
            Warn "Failed to update Claude Desktop config: $_"
        }
    }

    $vscodeMcp = Join-Path $pluginRoot ".vscode\mcp.json"
    if (-not (Test-Path (Join-Path $pluginRoot ".vscode"))) {
        StartAction "Create VS Code config directory"
        New-Item -ItemType Directory -Path (Join-Path $pluginRoot ".vscode") -Force | Out-Null
    }
    $vscodeMcpContent = @"
{
  "servers": {
    "excel-mcp": {
      "command": "mcp-excel"
    }
  }
}
"@
    StartAction "Write VS Code MCP config"
    Set-Content -Path $vscodeMcp -Value $vscodeMcpContent -Encoding UTF8
    $registeredTargets += "VS Code"

    if ($registeredTargets.Count -gt 0) {
        Ok "Registered MCP server in: $($registeredTargets -join ', ')"
    } else {
        Log "No supported client settings were found. Only .mcp.json was written."
    }

    StartStep "7. Test stdio handshake"
    $initMsg = '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"setup-test","version":"1.0.0"}}}'
    $testPassed = $false

    try {
        StartAction "Start mcp-excel process"
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $mcpExePath
        $psi.UseShellExecute = $false
        $psi.RedirectStandardInput = $true
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.CreateNoWindow = $true
        $proc = [System.Diagnostics.Process]::Start($psi)

        StartAction "Send initialize request"
        $proc.StandardInput.WriteLine($initMsg)
        $proc.StandardInput.Flush()

        StartAction "Wait for server response"
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        $response = ""
        while ($sw.ElapsedMilliseconds -lt 10000) {
            if ($proc.StandardOutput.Peek() -ge 0) {
                $line = $proc.StandardOutput.ReadLine()
                if ($line) {
                    $response = $line
                    break
                }
            }
            Start-Sleep -Milliseconds 200
        }

        try {
            $proc.Kill()
        } catch {
        }

        if ($response -match '"result"' -or $response -match '"serverInfo"' -or $response -match '"capabilities"') {
            $testPassed = $true
            Ok "stdio handshake succeeded"
        } elseif ($response) {
            Log "Server response: $response"
            Warn "Received an unexpected response. Verify MCP behavior in the client."
        } else {
            Warn "No response within 10 seconds. Check whether Excel can start correctly."
        }
    } catch {
        Warn "Failed to run handshake test: $_"
    }

    Write-Host ""
    Write-Host "====================================================" -ForegroundColor Cyan
    Write-Host " mcp-server-excel setup complete ($version)" -ForegroundColor Cyan
    Write-Host "====================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Executable:   $mcpExePath"
    if (Test-Path $cliExePath) {
        Write-Host "  CLI:          $cliExePath"
    }
    Write-Host "  PATH:         registered"
    Write-Host "  Config file:  $mcpJsonPath"
    Write-Host ""
    if ($testPassed) {
        Write-Host "  [TEST] stdio handshake: PASS" -ForegroundColor Green
    } else {
        Write-Host "  [TEST] stdio handshake: needs manual check" -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host "  Example prompts:"
    Write-Host "    > Open a new Excel file and write 'test' into A1"
    Write-Host "    > Show the Excel window"
    Write-Host ""
    Write-Host "  Close other Excel files before using the MCP server."
    Write-Host "====================================================" -ForegroundColor Cyan
} catch {
    $invocation = $_.InvocationInfo
    Write-Host ""
    Write-Host "[FAIL] Stage: $script:CurrentStage" -ForegroundColor Red
    Write-Host "[FAIL] Action: $script:CurrentAction" -ForegroundColor Red
    Write-Host "[FAIL] Error: $($_.Exception.Message)" -ForegroundColor Red
    if ($invocation) {
        if ($invocation.ScriptLineNumber) {
            Write-Host "[FAIL] Line: $($invocation.ScriptLineNumber)" -ForegroundColor Red
        }
        if ($invocation.Line) {
            Write-Host "[FAIL] Code: $($invocation.Line.Trim())" -ForegroundColor DarkRed
        }
    }
    exit 1
}
