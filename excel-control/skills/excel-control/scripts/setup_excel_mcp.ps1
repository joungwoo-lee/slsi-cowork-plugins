<#
.SYNOPSIS
    mcp-server-excel 원클릭 설치 스크립트 (Windows PowerShell 5.1+)
.DESCRIPTION
    1. Windows 환경 확인
    2. GitHub API에서 최신 릴리즈를 자동 감지
    3. MCP Server zip + CLI zip 다운로드 및 추출
    4. mcp-excel.exe 실제 위치를 찾아서 PATH 등록
    5. 플러그인 .mcp.json에 실행 경로 기입
    6. Claude Code / Claude Desktop / OpenCode / VS Code 설정 파일에 MCP 서버 등록
    7. stdio 핸드셰이크로 실제 동작 검증
.NOTES
    실행: powershell -ExecutionPolicy Bypass -File setup_excel_mcp.ps1
#>

$ErrorActionPreference = "Stop"
$script:CurrentStage = "초기화"
$script:CurrentAction = "시작 전"

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
function Fail($msg) {
    Write-Host "[FAIL] 단계: $script:CurrentStage" -ForegroundColor Red
    Write-Host "[FAIL] 작업: $script:CurrentAction" -ForegroundColor Red
    Write-Host "[FAIL] $msg" -ForegroundColor Red
    exit 1
}
function StartStep($msg) {
    $script:CurrentStage = $msg
    $script:CurrentAction = "대기"
    Write-Host ""
    Write-Host "=== $msg ===" -ForegroundColor Cyan
}
function StartAction($msg) {
    $script:CurrentAction = $msg
    Write-Host " -> $msg"
}
function Remove-JsonComments($text) {
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
    # ── 1. Windows 확인 ─────────────────────────────────────
    StartStep "1. Windows 환경 확인"
    StartAction "운영체제 확인"

    if ($env:OS -ne "Windows_NT") {
        Fail "Windows 환경에서만 실행 가능합니다."
    }

    # ── 2. GitHub API로 최신 릴리즈 감지 ────────────────────
    StartStep "2. 최신 릴리즈 확인"
    StartAction "GitHub API 호출"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $release = Invoke-RestMethod -Uri $GH_API -Headers @{ "User-Agent" = "excel-mcp-setup" }

    $version = $release.tag_name
    Log "   최신 버전: $version"

    $mcpAsset = $release.assets | Where-Object { $_.name -like "ExcelMcp-MCP-Server-*-windows.zip" } | Select-Object -First 1
    $cliAsset = $release.assets | Where-Object { $_.name -like "ExcelMcp-CLI-*-windows.zip" } | Select-Object -First 1

    if (-not $mcpAsset) {
        Fail "MCP Server zip 에셋을 찾을 수 없습니다.`n   https://github.com/$GH_REPO/releases/latest"
    }

    $mcpUrl = $mcpAsset.browser_download_url
    if ($cliAsset) {
        $cliUrl = $cliAsset.browser_download_url
    } else {
        $cliUrl = $null
    }

    Log "   MCP Server: $($mcpAsset.name)"
    if ($cliUrl) { Log "   CLI:        $($cliAsset.name)" }

    # ── 3. 다운로드 및 설치 ─────────────────────────────────
    StartStep "3. 다운로드 및 설치"

    if (Test-Path $INSTALL_DIR) {
        StartAction "기존 설치 디렉토리 삭제"
        Log "   기존 설치 디렉토리 정리: $INSTALL_DIR"
        Remove-Item $INSTALL_DIR -Recurse -Force
    }

    StartAction "설치 및 임시 디렉토리 생성"
    New-Item -ItemType Directory -Path $INSTALL_DIR -Force | Out-Null
    $tempDir = Join-Path $env:TEMP "excel-mcp-setup-$(Get-Random)"
    New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

    try {
        $mcpZip = Join-Path $tempDir "mcp-server.zip"
        StartAction "MCP Server ZIP 다운로드"
        Log "   MCP Server 다운로드 중... ($mcpUrl)"
        Invoke-WebRequest -Uri $mcpUrl -OutFile $mcpZip -UseBasicParsing

        $extractDir = Join-Path $tempDir "extracted-mcp"
        StartAction "MCP Server ZIP 압축 해제"
        Expand-Archive -Path $mcpZip -DestinationPath $extractDir -Force

        StartAction "mcp-excel.exe 위치 탐색"
        $foundExe = Get-ChildItem -Path $extractDir -Filter $EXE_NAME -Recurse | Select-Object -First 1
        if (-not $foundExe) {
            Fail "zip 내에서 $EXE_NAME 을 찾을 수 없습니다. 추출 경로: $extractDir"
        }

        $exeSourceDir = $foundExe.DirectoryName
        StartAction "MCP Server 파일 설치 폴더로 복사"
        Copy-Item -Path "$exeSourceDir\*" -Destination $INSTALL_DIR -Recurse -Force
        Ok "MCP Server 설치 완료"

        if ($cliUrl) {
            $cliZip = Join-Path $tempDir "cli.zip"
            StartAction "CLI ZIP 다운로드"
            Log "   CLI 다운로드 중..."
            Invoke-WebRequest -Uri $cliUrl -OutFile $cliZip -UseBasicParsing

            $extractCliDir = Join-Path $tempDir "extracted-cli"
            StartAction "CLI ZIP 압축 해제"
            Expand-Archive -Path $cliZip -DestinationPath $extractCliDir -Force

            StartAction "excelcli.exe 위치 탐색"
            $foundCli = Get-ChildItem -Path $extractCliDir -Filter $CLI_NAME -Recurse | Select-Object -First 1
            if ($foundCli) {
                StartAction "CLI 파일 설치 폴더로 복사"
                Copy-Item -Path "$($foundCli.DirectoryName)\*" -Destination $INSTALL_DIR -Recurse -Force
                Ok "CLI 설치 완료"
            } else {
                Warn "CLI zip 내에서 $CLI_NAME 을 찾을 수 없습니다. 건너뜁니다."
            }
        }
    } finally {
        StartAction "임시 폴더 정리"
        Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    }

    $mcpExePath = Join-Path $INSTALL_DIR $EXE_NAME
    $cliExePath = Join-Path $INSTALL_DIR $CLI_NAME

    if (-not (Test-Path $mcpExePath)) {
        Fail "$EXE_NAME 이 설치 경로에 없습니다: $mcpExePath"
    }
    Log "   설치 경로: $mcpExePath"

    # ── 4. PATH 등록 ────────────────────────────────────────
    StartStep "4. PATH 환경변수 등록"
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($userPath -notlike "*$INSTALL_DIR*") {
        StartAction "사용자 PATH에 설치 폴더 추가"
        [Environment]::SetEnvironmentVariable("Path", "$userPath;$INSTALL_DIR", "User")
        $env:Path = "$env:Path;$INSTALL_DIR"
        Ok "PATH에 $INSTALL_DIR 추가됨 (현재 세션 + 영구)"
    } else {
        StartAction "기존 PATH 등록 상태 확인"
        Log "   이미 PATH에 등록되어 있습니다."
    }

    # ── 5. .mcp.json 생성 ──────────────────────────────────
    StartStep "5. 플러그인 .mcp.json 설정"
    StartAction "플러그인 루트 계산"
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
    StartAction ".mcp.json 파일 쓰기"
    Set-Content -Path $mcpJsonPath -Value $mcpJsonContent -Encoding UTF8
    Ok ".mcp.json 설정 완료: $mcpJsonPath"

    # ── 6. AI 에이전트 설정 파일 등록 (선택) ────────────────
    StartStep "6. AI 에이전트 설정 파일 등록"
    $registeredTargets = @()

    $claudeSettings = Join-Path $env:USERPROFILE ".claude\settings.json"
    if (Test-Path $claudeSettings) {
        try {
            StartAction "Claude Code 설정 업데이트"
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

    $claudeDesktop = Join-Path $env:APPDATA "Claude\claude_desktop_config.json"
    if (Test-Path $claudeDesktop) {
        try {
            StartAction "Claude Desktop 설정 업데이트"
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

    $openCodeConfigDir = Join-Path $env:USERPROFILE ".config\opencode"
    $openCodeJsonPath = Join-Path $openCodeConfigDir "opencode.json"
    $openCodeJsoncPath = Join-Path $openCodeConfigDir "opencode.jsonc"
    if (Test-Path $openCodeJsonPath) {
        $openCodeConfigPath = $openCodeJsonPath
    } elseif (Test-Path $openCodeJsoncPath) {
        $openCodeConfigPath = $openCodeJsoncPath
    } else {
        $openCodeConfigPath = $openCodeJsonPath
    }

    try {
        StartAction "OpenCode 설정 업데이트"
        if (-not (Test-Path $openCodeConfigDir)) {
            New-Item -ItemType Directory -Path $openCodeConfigDir -Force | Out-Null
        }
        if (Test-Path $openCodeConfigPath) {
            $openCodeConfigRaw = Get-Content $openCodeConfigPath -Raw -Encoding UTF8
            $openCodeConfig = (Remove-JsonComments $openCodeConfigRaw) | ConvertFrom-Json
        } else {
            $openCodeConfig = [PSCustomObject]@{}
        }
        if (-not $openCodeConfig.PSObject.Properties["mcp"]) {
            $openCodeConfig | Add-Member -NotePropertyName "mcp" -NotePropertyValue ([PSCustomObject]@{})
        }
        $openCodeConfig.mcp | Add-Member -NotePropertyName "excel-mcp" -NotePropertyValue ([PSCustomObject]@{
            type = "local"
            command = @($mcpExePath)
            enabled = $true
        }) -Force
        $openCodeConfig | ConvertTo-Json -Depth 10 | Set-Content $openCodeConfigPath -Encoding UTF8
        $registeredTargets += "OpenCode"
    } catch {
        Warn "OpenCode 설정 업데이트 실패: $_"
    }

    $vscodeMcp = Join-Path $pluginRoot ".vscode\mcp.json"
    if (-not (Test-Path (Join-Path $pluginRoot ".vscode"))) {
        StartAction "VS Code 설정 디렉토리 생성"
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
    StartAction "VS Code MCP 설정 파일 쓰기"
    Set-Content -Path $vscodeMcp -Value $vscodeMcpContent -Encoding UTF8
    $registeredTargets += "VS Code"

    if ($registeredTargets.Count -gt 0) {
        Ok "MCP 서버 등록 완료: $($registeredTargets -join ', ')"
    } else {
        Log "   감지된 AI 에이전트 설정 파일이 없습니다. .mcp.json만 설정되었습니다."
    }

    # ── 7. stdio 핸드셰이크 테스트 ──────────────────────────
    StartStep "7. MCP stdio 핸드셰이크 테스트"
    $initMsg = '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"setup-test","version":"1.0.0"}}}'
    $testPassed = $false

    try {
        StartAction "mcp-excel 프로세스 시작"
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $mcpExePath
        $psi.UseShellExecute = $false
        $psi.RedirectStandardInput = $true
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.CreateNoWindow = $true
        $proc = [System.Diagnostics.Process]::Start($psi)

        StartAction "initialize 요청 전송"
        $proc.StandardInput.WriteLine($initMsg)
        $proc.StandardInput.Flush()

        StartAction "서버 응답 대기"
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
    Write-Host "    > 엑셀 창을 띄워줘 (백그라운드 -> 화면 표시)"
    Write-Host ""
    Write-Host "  주의: 작업 전 다른 엑셀 파일은 모두 닫아주세요"
    Write-Host "====================================================" -ForegroundColor Cyan
} catch {
    $invocation = $_.InvocationInfo
    Write-Host ""
    Write-Host "[FAIL] 단계: $script:CurrentStage" -ForegroundColor Red
    Write-Host "[FAIL] 작업: $script:CurrentAction" -ForegroundColor Red
    Write-Host "[FAIL] 오류: $($_.Exception.Message)" -ForegroundColor Red
    if ($invocation) {
        if ($invocation.ScriptLineNumber) {
            Write-Host "[FAIL] 줄: $($invocation.ScriptLineNumber)" -ForegroundColor Red
        }
        if ($invocation.Line) {
            Write-Host "[FAIL] 코드: $($invocation.Line.Trim())" -ForegroundColor DarkRed
        }
    }
    exit 1
}
