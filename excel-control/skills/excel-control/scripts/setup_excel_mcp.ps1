<#
.SYNOPSIS
    Minimal installer for mcp-server-excel on Windows PowerShell 5.1+

.NOTES
    Run with:
    powershell -ExecutionPolicy Bypass -File setup_excel_mcp.ps1
#>

$ErrorActionPreference = "Stop"

$Repo = "sbroenne/mcp-server-excel"
$LatestReleaseUrl = "https://github.com/$Repo/releases/latest"
$InstallDir = Join-Path $env:USERPROFILE "ExcelMcp"
$ExeName = "mcp-excel.exe"
$CliName = "excelcli.exe"
$UserAgent = "excel-mcp-setup"

function Step($msg) {
    Write-Host ""
    Write-Host "=== $msg ===" -ForegroundColor Cyan
}

function Info($msg) {
    Write-Host " -> $msg"
}

function Ok($msg) {
    Write-Host "[OK] $msg" -ForegroundColor Green
}

function Fail($msg) {
    Write-Host "[FAIL] $msg" -ForegroundColor Red
    exit 1
}

function DownloadFile($url, $destinationPath) {
    $webClient = New-Object System.Net.WebClient
    $webClient.Headers.Add("User-Agent", $UserAgent)
    try {
        $webClient.DownloadFile($url, $destinationPath)
    } finally {
        $webClient.Dispose()
    }
}

function ResolveLatestTag() {
    $request = [System.Net.HttpWebRequest]::Create($LatestReleaseUrl)
    $request.AllowAutoRedirect = $true
    $request.UserAgent = $UserAgent
    $request.Method = "GET"
    $request.Timeout = 30000

    $response = $request.GetResponse()
    try {
        $finalUrl = $response.ResponseUri.AbsoluteUri
    } finally {
        $response.Close()
    }

    if ($finalUrl -match '/tag/(v[^/]+)$') {
        return $Matches[1]
    }

    throw "Could not resolve latest release tag from $finalUrl"
}

function WritePluginConfig($exePath, $pluginRoot) {
    $mcpJsonPath = Join-Path $pluginRoot ".mcp.json"
    $escapedExePath = $exePath.Replace('\', '\\')
    $content = @"
{
  "mcpServers": {
    "excel-mcp": {
      "command": "$escapedExePath",
      "args": [],
      "env": {}
    }
  }
}
"@

    Set-Content -Path $mcpJsonPath -Value $content -Encoding UTF8
    Ok "Wrote $mcpJsonPath"
}

function WriteVsCodeConfig($pluginRoot) {
    $vscodeDir = Join-Path $pluginRoot ".vscode"
    $vscodeMcp = Join-Path $vscodeDir "mcp.json"

    if (-not (Test-Path $vscodeDir)) {
        New-Item -ItemType Directory -Path $vscodeDir -Force | Out-Null
    }

    $content = @"
{
  "servers": {
    "excel-mcp": {
      "command": "mcp-excel"
    }
  }
}
"@

    Set-Content -Path $vscodeMcp -Value $content -Encoding UTF8
    Ok "Wrote $vscodeMcp"
}

try {
    Step "1. Check Windows"
    Info "Verify operating system"
    if ($env:OS -ne "Windows_NT") {
        Fail "This script only runs on Windows."
    }

    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

    Step "2. Resolve release"
    Info "Resolve latest GitHub release"
    $version = ResolveLatestTag
    $versionNumber = $version.TrimStart('v')
    $mcpAssetName = "ExcelMcp-MCP-Server-$versionNumber-windows.zip"
    $cliAssetName = "ExcelMcp-CLI-$versionNumber-windows.zip"
    $mcpUrl = "https://github.com/$Repo/releases/download/$version/$mcpAssetName"
    $cliUrl = "https://github.com/$Repo/releases/download/$version/$cliAssetName"
    Write-Host "    Version: $version" -ForegroundColor Gray
    Write-Host "    MCP zip: $mcpAssetName" -ForegroundColor Gray
    Write-Host "    CLI zip: $cliAssetName" -ForegroundColor Gray

    Step "3. Install files"
    if (Test-Path $InstallDir) {
        Info "Remove previous install directory"
        Remove-Item $InstallDir -Recurse -Force
    }

    Info "Create install directory"
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null

    $tempDir = Join-Path $env:TEMP "excel-mcp-setup-$(Get-Random)"
    New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

    try {
        $mcpZip = Join-Path $tempDir $mcpAssetName
        $mcpExtractDir = Join-Path $tempDir "mcp"

        Info "Download MCP zip"
        DownloadFile $mcpUrl $mcpZip

        Info "Extract MCP zip"
        Expand-Archive -Path $mcpZip -DestinationPath $mcpExtractDir -Force

        Info "Find mcp-excel.exe"
        $foundExe = Get-ChildItem -Path $mcpExtractDir -Filter $ExeName -Recurse | Select-Object -First 1
        if (-not $foundExe) {
            Fail "Could not find $ExeName after extracting $mcpAssetName"
        }

        Info "Copy MCP files"
        Copy-Item -Path "$($foundExe.DirectoryName)\*" -Destination $InstallDir -Recurse -Force
        Ok "Installed MCP Server"

        $cliZip = Join-Path $tempDir $cliAssetName
        $cliExtractDir = Join-Path $tempDir "cli"

        try {
            Info "Download CLI zip"
            DownloadFile $cliUrl $cliZip

            Info "Extract CLI zip"
            Expand-Archive -Path $cliZip -DestinationPath $cliExtractDir -Force

            Info "Find excelcli.exe"
            $foundCli = Get-ChildItem -Path $cliExtractDir -Filter $CliName -Recurse | Select-Object -First 1
            if ($foundCli) {
                Info "Copy CLI files"
                Copy-Item -Path "$($foundCli.DirectoryName)\*" -Destination $InstallDir -Recurse -Force
                Ok "Installed CLI"
            } else {
                Write-Host "[WARN] Could not find $CliName after extracting $cliAssetName" -ForegroundColor Yellow
            }
        } catch {
            Write-Host "[WARN] CLI install skipped: $($_.Exception.Message)" -ForegroundColor Yellow
        }
    } finally {
        Info "Clean temp directory"
        Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    }

    $mcpExePath = Join-Path $InstallDir $ExeName
    if (-not (Test-Path $mcpExePath)) {
        Fail "$ExeName was not installed to $mcpExePath"
    }

    Step "4. Update PATH"
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($userPath -notlike "*$InstallDir*") {
        Info "Append install directory to user PATH"
        [Environment]::SetEnvironmentVariable("Path", "$userPath;$InstallDir", "User")
        $env:Path = "$env:Path;$InstallDir"
        Ok "PATH updated"
    } else {
        Write-Host "    PATH already contains $InstallDir" -ForegroundColor Gray
    }

    Step "5. Write local config"
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $pluginRoot = (Resolve-Path (Join-Path $scriptDir "..\..\..")).Path
    Info "Write plugin .mcp.json"
    WritePluginConfig $mcpExePath $pluginRoot
    Info "Write VS Code MCP config"
    WriteVsCodeConfig $pluginRoot

    Step "6. Test process start"
    try {
        Info "Start mcp-excel"
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $mcpExePath
        $psi.UseShellExecute = $false
        $psi.RedirectStandardInput = $true
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.CreateNoWindow = $true
        $proc = [System.Diagnostics.Process]::Start($psi)
        Start-Sleep -Milliseconds 800
        if (-not $proc.HasExited) {
            $proc.Kill()
            Ok "mcp-excel started successfully"
        } else {
            Write-Host "[WARN] mcp-excel exited immediately. Check Excel availability on this machine." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "[WARN] Process start test failed: $($_.Exception.Message)" -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "====================================================" -ForegroundColor Cyan
    Write-Host " mcp-server-excel setup complete ($version)" -ForegroundColor Cyan
    Write-Host "====================================================" -ForegroundColor Cyan
    Write-Host "  Executable:   $mcpExePath"
    Write-Host "  Install dir:  $InstallDir"
    Write-Host "  Plugin root:  $pluginRoot"
    Write-Host "====================================================" -ForegroundColor Cyan
} catch {
    Write-Host ""
    Write-Host "[FAIL] $($_.Exception.Message)" -ForegroundColor Red
    if ($_.InvocationInfo) {
        Write-Host "[FAIL] Line: $($_.InvocationInfo.ScriptLineNumber)" -ForegroundColor Red
        if ($_.InvocationInfo.Line) {
            Write-Host "[FAIL] Code: $($_.InvocationInfo.Line.Trim())" -ForegroundColor DarkRed
        }
    }
    exit 1
}
