# setup_excel_mcp.ps1 - mcp-server-excel 설치 및 MCP stdio 연결 설정
# Windows 환경 전용 (PowerShell 5.1+)

$ErrorActionPreference = "Stop"

# ── 설정값 ──────────────────────────────────────────────
$ReleaseVersion = "1.8.43"
$ReleaseUrl = "https://github.com/sbroenne/mcp-server-excel/releases/download/v$ReleaseVersion/ExcelMcp-MCP-Server-$ReleaseVersion-windows.zip"
$CliUrl = "https://github.com/sbroenne/mcp-server-excel/releases/download/v$ReleaseVersion/ExcelMcp-CLI-$ReleaseVersion-windows.zip"

$InstallDir = Join-Path $env:USERPROFILE "ExcelMcp"
$McpExe = Join-Path $InstallDir "mcp-excel.exe"
$CliExe = Join-Path $InstallDir "excelcli.exe"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PluginRoot = (Resolve-Path (Join-Path $ScriptDir "..\..\..")).Path
$McpJson = Join-Path $PluginRoot ".mcp.json"

# ── 헬퍼 함수 ──────────────────────────────────────────
function Log($msg)  { Write-Host ">>> $msg" }
function Ok($msg)   { Write-Host "[OK] $msg" -ForegroundColor Green }
function Fail($msg) { Write-Host "[FAIL] $msg" -ForegroundColor Red; exit 1 }

# ── 1. 환경 확인 ──────────────────────────────────────
Log "1. 환경 확인..."

# Windows 확인
if ($env:OS -ne "Windows_NT") {
    Fail "이 스크립트는 Windows 환경에서만 동작합니다."
}
Log "   Windows 환경 확인됨"

# Excel 설치 확인
$excelPath = Get-Command "EXCEL.EXE" -ErrorAction SilentlyContinue
if (-not $excelPath) {
    # 레지스트리에서 확인
    $excelReg = Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\excel.exe" -ErrorAction SilentlyContinue
    if (-not $excelReg) {
        Write-Host "[WARN] Excel 실행 파일을 찾을 수 없습니다. Excel 2016 이상이 설치되어 있는지 확인해 주세요." -ForegroundColor Yellow
    } else {
        Log "   Microsoft Excel 설치 확인됨: $($excelReg.'(Default)')"
    }
} else {
    Log "   Microsoft Excel 설치 확인됨: $($excelPath.Source)"
}

# ── 2. 다운로드 및 설치 ────────────────────────────────
Log "2. mcp-server-excel 다운로드 (v$ReleaseVersion)..."
Log "   설치 경로: $InstallDir"

if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}

$TempDir = Join-Path $env:TEMP "excel-mcp-setup"
if (Test-Path $TempDir) { Remove-Item $TempDir -Recurse -Force }
New-Item -ItemType Directory -Path $TempDir -Force | Out-Null

# MCP Server 다운로드
Log "   MCP Server 다운로드 중..."
$mcpZip = Join-Path $TempDir "mcp-server.zip"
Invoke-WebRequest -Uri $ReleaseUrl -OutFile $mcpZip -UseBasicParsing
Expand-Archive -Path $mcpZip -DestinationPath $InstallDir -Force
Ok "MCP Server (mcp-excel.exe) 설치 완료"

# CLI 도구 다운로드
Log "   CLI 도구 다운로드 중..."
$cliZip = Join-Path $TempDir "cli.zip"
Invoke-WebRequest -Uri $CliUrl -OutFile $cliZip -UseBasicParsing
Expand-Archive -Path $cliZip -DestinationPath $InstallDir -Force
Ok "CLI (excelcli.exe) 설치 완료"

# 임시 디렉토리 정리
Remove-Item $TempDir -Recurse -Force

# 실행 파일 확인
if (-not (Test-Path $McpExe)) {
    Fail "mcp-excel.exe 파일을 찾을 수 없습니다: $McpExe"
}

# ── 3. .mcp.json 업데이트 ──────────────────────────────
Log "3. MCP 설정 업데이트 (.mcp.json)..."

$mcpConfig = @{
    mcpServers = @{
        "excel-mcp" = @{
            command = $McpExe
            args = @()
            env = @{}
        }
    }
} | ConvertTo-Json -Depth 4

Set-Content -Path $McpJson -Value $mcpConfig -Encoding UTF8
Ok ".mcp.json 설정 완료"

# ── 4. Claude Code settings.json 등록 (선택) ──────────
$claudeSettings = Join-Path $env:USERPROFILE ".claude\settings.json"
if (Test-Path $claudeSettings) {
    Log "4. Claude Code 설정에 MCP 서버 등록..."
    try {
        $settings = Get-Content $claudeSettings -Raw | ConvertFrom-Json

        # mcpServers 속성이 없으면 생성
        if (-not $settings.PSObject.Properties["mcpServers"]) {
            $settings | Add-Member -NotePropertyName "mcpServers" -NotePropertyValue @{}
        }

        $settings.mcpServers | Add-Member -NotePropertyName "excel-mcp" -NotePropertyValue @{
            command = $McpExe
            args = @()
            env = @{}
        } -Force

        $settings | ConvertTo-Json -Depth 10 | Set-Content $claudeSettings -Encoding UTF8
        Ok "Claude Code settings.json에 excel-mcp 등록 완료"
    } catch {
        Write-Host "[WARN] settings.json 자동 업데이트 실패: $_" -ForegroundColor Yellow
        Write-Host "   수동으로 추가해 주세요." -ForegroundColor Yellow
    }
} else {
    Log "4. Claude Code settings.json이 없습니다. .mcp.json만 설정됩니다."
}

# ── 5. OpenCode 설정 등록 (선택) ──────────────────────
$opencodeConfig = Join-Path $env:USERPROFILE ".opencode\config.json"
if (Test-Path $opencodeConfig) {
    Log "5. OpenCode 설정에 MCP 서버 등록..."
    try {
        $ocConfig = Get-Content $opencodeConfig -Raw | ConvertFrom-Json

        if (-not $ocConfig.PSObject.Properties["mcpServers"]) {
            $ocConfig | Add-Member -NotePropertyName "mcpServers" -NotePropertyValue @{}
        }

        $ocConfig.mcpServers | Add-Member -NotePropertyName "excel-mcp" -NotePropertyValue @{
            type = "stdio"
            command = $McpExe
            args = @()
        } -Force

        $ocConfig | ConvertTo-Json -Depth 10 | Set-Content $opencodeConfig -Encoding UTF8
        Ok "OpenCode config.json에 excel-mcp 등록 완료"
    } catch {
        Write-Host "[WARN] OpenCode config.json 자동 업데이트 실패: $_" -ForegroundColor Yellow
    }
} else {
    Log "5. OpenCode config.json이 없습니다. 건너뜁니다."
}

# ── 6. 연결 테스트 ────────────────────────────────────
Log "6. MCP 서버 연결 테스트..."

$initRequest = '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"setup-test","version":"1.0"}}}'

try {
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo.FileName = $McpExe
    $process.StartInfo.UseShellExecute = $false
    $process.StartInfo.RedirectStandardInput = $true
    $process.StartInfo.RedirectStandardOutput = $true
    $process.StartInfo.RedirectStandardError = $true
    $process.StartInfo.CreateNoWindow = $true
    $process.Start() | Out-Null

    $process.StandardInput.WriteLine($initRequest)
    $process.StandardInput.Close()

    $output = ""
    $task = $process.StandardOutput.ReadLineAsync()
    if ($task.Wait(10000)) {
        $output = $task.Result
    }

    $process.Kill() 2>$null

    if ($output -match '"result"') {
        Ok "MCP 서버 stdio 통신 정상!"
    } else {
        Write-Host "[WARN] MCP 서버 테스트 응답을 확인할 수 없습니다." -ForegroundColor Yellow
        Write-Host "   Excel이 설치되어 있고 다른 엑셀 파일이 닫혀 있는지 확인해 주세요." -ForegroundColor Yellow
    }
} catch {
    Write-Host "[WARN] MCP 서버 테스트 실행 실패: $_" -ForegroundColor Yellow
    Write-Host "   실제 AI 에이전트 세션에서 연결을 시도해 보세요." -ForegroundColor Yellow
}

# ── 완료 ──────────────────────────────────────────────
Write-Host ""
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host " mcp-server-excel 설치 및 설정 완료!" -ForegroundColor Cyan
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  MCP Server: $McpExe"
Write-Host "  CLI Tool:   $CliExe"
Write-Host "  설정 파일:  $McpJson"
Write-Host ""
Write-Host "  사용법:"
Write-Host "    - AI 에이전트에서 엑셀 관련 작업을 요청하면 자동으로 MCP 도구가 호출됩니다."
Write-Host "    - '엑셀 창을 띄워줘' 또는 'Show me Excel'로 실시간 확인 가능"
Write-Host "    - 작업 전 다른 엑셀 파일은 닫아주세요 (파일 독점 방지)"
Write-Host ""
Write-Host "  테스트:"
Write-Host "    '새로운 엑셀 파일을 열고, A1에 테스트라고 적어줘'"
Write-Host "====================================================" -ForegroundColor Cyan
