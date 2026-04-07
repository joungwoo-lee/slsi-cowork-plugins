<#
.SYNOPSIS
    mcp-server-excel 원클릭 설치 스크립트 (Windows PowerShell 5.1+)
.DESCRIPTION
    1. GitHub API에서 최신 릴리즈를 자동 감지
    2. MCP Server zip + CLI zip 다운로드 및 추출
    3. mcp-excel.exe 실제 위치를 찾아서 PATH 등록
    4. 플러그인 .mcp.json에 실행 경로 기입
    5. (선택) Claude Code / OpenCode 설정 파일에 MCP 서버 등록
    6. stdio 핸드셰이크로 실제 동작 검증
.NOTES
    실행: powershell -ExecutionPolicy Bypass -File setup_excel_mcp.ps1
#>

$ErrorActionPreference = "Stop"

# ── 설정 ────────────────────────────────────────────────
$GH_REPO       = "sbroenne/mcp-server-excel"
$GH_API        = "https://api.github.com/repos/$GH_REPO/releases/latest"
$INSTALL_DIR   = Join-Path $env:USERPROFILE "ExcelMcp"
$EXE_NAME      = "mcp-excel.exe"
$CLI_NAME      = "excelcli.exe"

# ── 헬퍼 ────────────────────────────────────────────────
function Log($msg)  { Write-Host ">>> $msg" }
function Ok($msg)   { Write-Host "[OK] $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "[FAIL] $msg" -ForegroundColor Red; exit 1 }

# ── 1. Windows + Excel 확인 ─────────────────────────────
Log "1. 환경 확인..."

if ($env:OS -ne "Windows_NT") {
    Fail "Windows 환경에서만 실행 가능합니다."
}

# Excel COM 객체 생성으로 확실하게 확인
try {
    $excel = New-Object -ComObject Excel.Application
    $excelVer = $excel.Version
    $excel.Quit()
    [System.Runtime.Interopservices.Marshal]::ReleaseComObject($excel) | Out-Null
    Log "   Excel $excelVer 확인됨"
} catch {
    Warn "Excel COM 객체를 생성할 수 없습니다. Excel 2016+ 설치를 확인해 주세요."
    Warn "   설치는 계속 진행합니다. 실행 시점에 Excel이 필요합니다."
}

# ── 2. GitHub API로 최신 릴리즈 감지 ────────────────────
Log "2. 최신 릴리즈 확인 중..."

try {
    # TLS 1.2 강제 (Windows 10 이전 호환)
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $release = Invoke-RestMethod -Uri $GH_API -Headers @{ "User-Agent" = "excel-mcp-setup" }
} catch {
    Fail "GitHub API 호출 실패: $_`n   네트워크 연결 또는 API rate limit을 확인하세요."
}

$version = $release.tag_name  # e.g. "v1.8.43"
Log "   최신 버전: $version"

# 에셋 URL 찾기 (MCP Server zip)
$mcpAsset = $release.assets | Where-Object { $_.name -like "ExcelMcp-MCP-Server-*-windows.zip" } | Select-Object -First 1
$cliAsset = $release.assets | Where-Object { $_.name -like "ExcelMcp-CLI-*-windows.zip" } | Select-Object -First 1

if (-not $mcpAsset) {
    Fail "MCP Server zip 에셋을 찾을 수 없습니다. 릴리즈 페이지를 확인하세요:`n   https://github.com/$GH_REPO/releases/latest"
}

$mcpUrl = $mcpAsset.browser_download_url
$cliUrl = if ($cliAsset) { $cliAsset.browser_download_url } else { $null }

Log "   MCP Server: $($mcpAsset.name)"
if ($cliUrl) { Log "   CLI:        $($cliAsset.name)" }

# ── 3. 다운로드 및 추출 ─────────────────────────────────
Log "3. 다운로드 및 설치..."

# 설치 디렉토리 준비
if (Test-Path $INSTALL_DIR) {
    Log "   기존 설치 디렉토리 정리: $INSTALL_DIR"
    Remove-Item $INSTALL_DIR -Recurse -Force
}
New-Item -ItemType Directory -Path $INSTALL_DIR -Force | Out-Null

$tempDir = Join-Path $env:TEMP "excel-mcp-setup-$(Get-Random)"
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

try {
    # MCP Server 다운로드
    $mcpZip = Join-Path $tempDir "mcp-server.zip"
    Log "   MCP Server 다운로드 중... ($mcpUrl)"
    Invoke-WebRequest -Uri $mcpUrl -OutFile $mcpZip -UseBasicParsing

    # 추출 (임시 폴더에 먼저 풀고 구조 확인)
    $extractDir = Join-Path $tempDir "extracted-mcp"
    Expand-Archive -Path $mcpZip -DestinationPath $extractDir -Force

    # mcp-excel.exe 실제 위치 찾기 (zip 내부 구조가 다를 수 있음)
    $foundExe = Get-ChildItem -Path $extractDir -Filter $EXE_NAME -Recurse | Select-Object -First 1
    if (-not $foundExe) {
        Fail "zip 내에서 $EXE_NAME 을 찾을 수 없습니다.`n   추출 경로: $extractDir`n   내용: $(Get-ChildItem $extractDir -Recurse | Select-Object -ExpandProperty FullName)"
    }

    # exe가 있는 디렉토리의 모든 파일을 설치 디렉토리로 복사
    $exeSourceDir = $foundExe.DirectoryName
    Copy-Item -Path "$exeSourceDir\*" -Destination $INSTALL_DIR -Recurse -Force
    Ok "MCP Server 설치 완료"

    # CLI 다운로드 (선택)
    if ($cliUrl) {
        $cliZip = Join-Path $tempDir "cli.zip"
        Log "   CLI 다운로드 중..."
        Invoke-WebRequest -Uri $cliUrl -OutFile $cliZip -UseBasicParsing
        $extractCliDir = Join-Path $tempDir "extracted-cli"
        Expand-Archive -Path $cliZip -DestinationPath $extractCliDir -Force
        $foundCli = Get-ChildItem -Path $extractCliDir -Filter $CLI_NAME -Recurse | Select-Object -First 1
        if ($foundCli) {
            Copy-Item -Path "$($foundCli.DirectoryName)\*" -Destination $INSTALL_DIR -Recurse -Force
            Ok "CLI 설치 완료"
        } else {
            Warn "CLI zip 내에서 $CLI_NAME 을 찾을 수 없습니다. 건너뜁니다."
        }
    }
} finally {
    # 임시 파일 정리
    Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue
}

# 설치된 exe 경로 확정
$mcpExePath = Join-Path $INSTALL_DIR $EXE_NAME
$cliExePath = Join-Path $INSTALL_DIR $CLI_NAME

if (-not (Test-Path $mcpExePath)) {
    Fail "$EXE_NAME 이 설치 경로에 없습니다: $mcpExePath"
}
Log "   설치 경로: $mcpExePath"

# ── 4. PATH 등록 ────────────────────────────────────────
Log "4. PATH 환경변수 등록..."

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$INSTALL_DIR*") {
    [Environment]::SetEnvironmentVariable("Path", "$userPath;$INSTALL_DIR", "User")
    $env:Path = "$env:Path;$INSTALL_DIR"
    Ok "PATH에 $INSTALL_DIR 추가됨 (현재 세션 + 영구)"
} else {
    Log "   이미 PATH에 등록되어 있습니다."
}

# ── 5. .mcp.json 생성 ──────────────────────────────────
Log "5. 플러그인 .mcp.json 설정..."

# 스크립트 위치 기준으로 플러그인 루트 계산
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pluginRoot = (Resolve-Path (Join-Path $scriptDir "..\..\..")).Path
$mcpJsonPath = Join-Path $pluginRoot ".mcp.json"

# PATH에 등록했으므로 exe 이름만으로도 동작, 풀패스도 함께 기록
$mcpJsonContent = @"
{
  "mcpServers": {
    "excel-mcp": {
      "command": "$($mcpExePath.Replace('\','\\'))",
      "args": [],
      "env": {}
    }
  }
}
"@

Set-Content -Path $mcpJsonPath -Value $mcpJsonContent -Encoding UTF8
Ok ".mcp.json 설정 완료: $mcpJsonPath"

# ── 6. Claude Code settings.json 등록 (선택) ────────────
Log "6. AI 에이전트 설정 파일에 MCP 서버 등록..."

$registeredTargets = @()

# Claude Code
$claudeSettings = Join-Path $env:USERPROFILE ".claude\settings.json"
if (Test-Path $claudeSettings) {
    try {
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
        Warn "Claude Code settings.json 업데이트 실패: $_"
    }
}

# Claude Desktop
$claudeDesktop = Join-Path $env:APPDATA "Claude\claude_desktop_config.json"
if (Test-Path $claudeDesktop) {
    try {
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
        Warn "Claude Desktop 설정 업데이트 실패: $_"
    }
}

# VS Code MCP (프로젝트 루트)
$vscodeMcp = Join-Path $pluginRoot ".vscode\mcp.json"
if (-not (Test-Path (Join-Path $pluginRoot ".vscode"))) {
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
Set-Content -Path $vscodeMcp -Value $vscodeMcpContent -Encoding UTF8
$registeredTargets += "VS Code"

if ($registeredTargets.Count -gt 0) {
    Ok "MCP 서버 등록 완료: $($registeredTargets -join ', ')"
} else {
    Log "   감지된 AI 에이전트 설정 파일이 없습니다. .mcp.json만 설정되었습니다."
}

# ── 7. stdio 핸드셰이크 테스트 ──────────────────────────
Log "7. MCP stdio 핸드셰이크 테스트..."

# JSON-RPC initialize 요청 (MCP 프로토콜 스펙)
$initMsg = '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"setup-test","version":"1.0.0"}}}'

$testPassed = $false
try {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $mcpExePath
    $psi.UseShellExecute = $false
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true

    $proc = [System.Diagnostics.Process]::Start($psi)

    # Content-Length 헤더 + 본문 전송 (일부 MCP 서버는 LSP 스타일 프레이밍 사용)
    # 먼저 raw JSON 시도
    $proc.StandardInput.WriteLine($initMsg)
    $proc.StandardInput.Flush()

    # 10초 대기하며 응답 읽기
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

    try { $proc.Kill() } catch {}

    if ($response -match '"result"' -or $response -match '"serverInfo"' -or $response -match '"capabilities"') {
        $testPassed = $true
        Ok "stdio 핸드셰이크 성공! 서버 응답 수신됨"
    } elseif ($response) {
        Log "   서버 응답: $response"
        Warn "예상과 다른 응답입니다. MCP 서버가 정상 동작하는지 에이전트에서 확인해 주세요."
    } else {
        Warn "10초 내 응답 없음. Excel이 실행 가능한 상태인지 확인해 주세요."
    }
} catch {
    Warn "테스트 프로세스 실행 실패: $_"
}

# ── 완료 ────────────────────────────────────────────────
Write-Host ""
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host " mcp-server-excel 설치 완료 ($version)" -ForegroundColor Cyan
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  실행 파일:  $mcpExePath"
if (Test-Path $cliExePath) {
    Write-Host "  CLI 도구:   $cliExePath"
}
Write-Host "  PATH:       등록됨 (mcp-excel 명령으로 실행 가능)"
Write-Host "  설정 파일:  $mcpJsonPath"
Write-Host ""
if ($testPassed) {
    Write-Host "  [TEST] stdio 핸드셰이크: PASS" -ForegroundColor Green
} else {
    Write-Host "  [TEST] stdio 핸드셰이크: 수동 확인 필요" -ForegroundColor Yellow
}
Write-Host ""
Write-Host "  사용법 (AI 에이전트 프롬프트):"
Write-Host "    > 새 엑셀 파일을 열고, A1에 '테스트'라고 적어줘"
Write-Host "    > 엑셀 창을 띄워줘 (백그라운드 → 화면 표시)"
Write-Host ""
Write-Host "  주의: 작업 전 다른 엑셀 파일은 모두 닫아주세요"
Write-Host "====================================================" -ForegroundColor Cyan
