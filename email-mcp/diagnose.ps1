# diagnose-email-mcp.ps1
# email-mcp -32000 Connection closed 진단 스크립트
# 사용법: PowerShell에서 powershell -ExecutionPolicy Bypass -File diagnose-email-mcp.ps1
# 옵션: -EmailMcpPath, -EmailConnectorPath 로 경로 명시 가능

[CmdletBinding()]
param(
    [string]$EmailMcpPath = "$env:USERPROFILE\.claude\skills\email-mcp",
    [string]$EmailConnectorPath = "$env:USERPROFILE\.claude\skills\email-connector",
    [string]$ClaudeConfig = "$env:APPDATA\Claude\claude_desktop_config.json"
)

$ErrorActionPreference = "Continue"
$results = @()
$failed = 0

function Check {
    param([string]$Name, [scriptblock]$Block)
    Write-Host ""
    Write-Host "=== [$Name] ===" -ForegroundColor Cyan
    try {
        $ok = & $Block
        if ($ok -eq $false) {
            $script:failed++
            Write-Host "  RESULT: FAIL" -ForegroundColor Red
            $script:results += [pscustomobject]@{Check=$Name; Status="FAIL"}
        } else {
            Write-Host "  RESULT: OK" -ForegroundColor Green
            $script:results += [pscustomobject]@{Check=$Name; Status="OK"}
        }
    } catch {
        $script:failed++
        Write-Host "  RESULT: ERROR - $_" -ForegroundColor Red
        $script:results += [pscustomobject]@{Check=$Name; Status="ERROR"}
    }
}

Write-Host "email-mcp Diagnostic" -ForegroundColor Yellow
Write-Host "EmailMcpPath        : $EmailMcpPath"
Write-Host "EmailConnectorPath  : $EmailConnectorPath"
Write-Host "ClaudeConfig        : $ClaudeConfig"

# --- 1. py launcher ---
Check "py launcher 존재" {
    $p = Get-Command py -ErrorAction SilentlyContinue
    if (-not $p) {
        Write-Host "  py 런처를 PATH에서 못 찾음. Python 공식 인스톨러로 'py launcher' 옵션 켜고 설치 필요." -ForegroundColor Yellow
        return $false
    }
    Write-Host "  py path: $($p.Source)"
    return $true
}

# --- 2. Python 3.9 64-bit ---
Check "Python 3.9 64-bit 확인" {
    $ver = & py -3.9 -c "import sys, platform; print(sys.version); print(platform.architecture()[0])" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  py -3.9 실행 실패. 출력:" -ForegroundColor Yellow
        Write-Host "  $ver"
        return $false
    }
    Write-Host "  $ver"
    if ($ver -notmatch "64bit") {
        Write-Host "  64-bit 아님. libpff-python wheel 못 씀." -ForegroundColor Yellow
        return $false
    }
    return $true
}

# --- 3. email-mcp 폴더 / server.py ---
Check "email-mcp\server.py 존재" {
    $sp = Join-Path $EmailMcpPath "server.py"
    if (-not (Test-Path $sp)) {
        Write-Host "  파일 없음: $sp" -ForegroundColor Yellow
        return $false
    }
    Write-Host "  $sp"
    return $true
}

# --- 4. email-connector 폴더 ---
Check "email-connector 폴더 존재" {
    if (-not (Test-Path $EmailConnectorPath)) {
        Write-Host "  폴더 없음: $EmailConnectorPath" -ForegroundColor Yellow
        return $false
    }
    $scripts = Join-Path $EmailConnectorPath "scripts"
    if (-not (Test-Path $scripts)) {
        Write-Host "  scripts/ 폴더 없음: $scripts" -ForegroundColor Yellow
        return $false
    }
    return $true
}

# --- 5. .env ---
Check "email-connector\.env 존재" {
    $envFile = Join-Path $EmailConnectorPath ".env"
    if (-not (Test-Path $envFile)) {
        $example = Join-Path $EmailConnectorPath ".env.example"
        if (Test-Path $example) {
            Write-Host "  .env 없음. .env.example 은 있음 → 복사 필요" -ForegroundColor Yellow
        } else {
            Write-Host "  .env / .env.example 둘 다 없음" -ForegroundColor Yellow
        }
        return $false
    }
    Write-Host "  $envFile"
    return $true
}

# --- 6. claude_desktop_config.json 존재 ---
Check "claude_desktop_config.json 존재" {
    if (-not (Test-Path $ClaudeConfig)) {
        Write-Host "  파일 없음: $ClaudeConfig" -ForegroundColor Yellow
        Write-Host "  Claude Desktop에 MCP 등록 자체가 안 된 상태." -ForegroundColor Yellow
        return $false
    }
    $size = (Get-Item $ClaudeConfig).Length
    Write-Host "  size: $size bytes"
    return $true
}

# --- 7. BOM 검사 ---
Check "config 파일 BOM 없음" {
    if (-not (Test-Path $ClaudeConfig)) { return $false }
    $bytes = [System.IO.File]::ReadAllBytes($ClaudeConfig)
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 239 -and $bytes[1] -eq 187 -and $bytes[2] -eq 191) {
        Write-Host "  ★ BOM 감지됨 (EF BB BF). Claude가 JSON 파싱 실패할 수 있음." -ForegroundColor Red
        Write-Host "  해결: VSCode에서 열고 우하단 'UTF-8 with BOM' → 'UTF-8'로 저장." -ForegroundColor Yellow
        return $false
    }
    Write-Host "  BOM 없음"
    return $true
}

# --- 8. JSON 파싱 ---
$configObj = $null
Check "config JSON 파싱 가능" {
    if (-not (Test-Path $ClaudeConfig)) { return $false }
    try {
        $script:configObj = Get-Content $ClaudeConfig -Raw -Encoding UTF8 | ConvertFrom-Json
        return $true
    } catch {
        Write-Host "  JSON 파싱 실패: $_" -ForegroundColor Red
        Write-Host "  대부분 백슬래시 한 개(\) 또는 trailing comma 문제." -ForegroundColor Yellow
        return $false
    }
}

# --- 9. email 항목 확인 ---
Check "mcpServers.email 항목 존재" {
    if (-not $configObj) { return $false }
    if (-not $configObj.mcpServers) {
        Write-Host "  mcpServers 키 없음" -ForegroundColor Yellow
        return $false
    }
    if (-not $configObj.mcpServers.email) {
        Write-Host "  mcpServers.email 항목 없음" -ForegroundColor Yellow
        Write-Host "  현재 등록된 서버: $($configObj.mcpServers.PSObject.Properties.Name -join ', ')"
        return $false
    }
    $entry = $configObj.mcpServers.email
    Write-Host "  command: $($entry.command)"
    Write-Host "  args   : $($entry.args -join ' ')"
    if ($entry.env) {
        Write-Host "  env    :"
        $entry.env.PSObject.Properties | ForEach-Object { Write-Host "    $($_.Name) = $($_.Value)" }
    }

    # args 안의 server.py 경로가 실제로 존재하는지
    $serverArg = $entry.args | Where-Object { $_ -match "server\.py$" } | Select-Object -First 1
    if ($serverArg -and -not (Test-Path $serverArg)) {
        Write-Host "  ★ args의 server.py 경로 실재 안함: $serverArg" -ForegroundColor Red
        return $false
    }

    # EMAIL_CONNECTOR_PATH 가 실제로 존재하는지
    if ($entry.env -and $entry.env.EMAIL_CONNECTOR_PATH) {
        $ecp = $entry.env.EMAIL_CONNECTOR_PATH
        if (-not (Test-Path $ecp)) {
            Write-Host "  ★ env.EMAIL_CONNECTOR_PATH 실재 안함: $ecp" -ForegroundColor Red
            return $false
        }
    }
    return $true
}

# --- 10. doctor.py 실행 ---
Check "email-connector doctor.py --skip-api" {
    $doc = Join-Path $EmailConnectorPath "scripts\doctor.py"
    if (-not (Test-Path $doc)) {
        Write-Host "  doctor.py 없음: $doc" -ForegroundColor Yellow
        return $false
    }
    $out = & py -3.9 $doc --skip-api 2>&1 | Out-String
    Write-Host $out
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  doctor 비정상 종료" -ForegroundColor Yellow
        return $false
    }
    if ($out -match "ok=false|FAIL|ERROR") {
        Write-Host "  doctor 출력에 실패 항목 있음 (위 메시지 확인)" -ForegroundColor Yellow
        return $false
    }
    return $true
}

# --- 11. 서버 stdio 스모크 테스트 (initialize 보내고 응답 확인) ---
Check "서버 initialize 응답 스모크 테스트" {
    $sp = Join-Path $EmailMcpPath "server.py"
    if (-not (Test-Path $sp)) { return $false }

    $initReq = '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"diag","version":"0"}}}'
    $tmpIn  = [System.IO.Path]::GetTempFileName()
    $tmpOut = [System.IO.Path]::GetTempFileName()
    $tmpErr = [System.IO.Path]::GetTempFileName()
    # MCP는 LSP 스타일 Content-Length 헤더 또는 line-delimited JSON 둘 다 가능 — 우선 line-delimited 시도
    [System.IO.File]::WriteAllText($tmpIn, $initReq + "`n", [System.Text.UTF8Encoding]::new($false))

    $envCopy = @{}
    if ($configObj -and $configObj.mcpServers.email.env) {
        $configObj.mcpServers.email.env.PSObject.Properties | ForEach-Object { $envCopy[$_.Name] = $_.Value }
    } else {
        $envCopy["EMAIL_CONNECTOR_PATH"] = $EmailConnectorPath
    }

    foreach ($k in $envCopy.Keys) { [System.Environment]::SetEnvironmentVariable($k, $envCopy[$k], "Process") }

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "py"
    $psi.Arguments = "-3.9 `"$sp`""
    $psi.RedirectStandardInput  = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError  = $true
    $psi.UseShellExecute = $false
    foreach ($k in $envCopy.Keys) { $psi.EnvironmentVariables[$k] = $envCopy[$k] }

    $proc = [System.Diagnostics.Process]::Start($psi)
    $proc.StandardInput.WriteLine($initReq)
    $proc.StandardInput.Flush()

    # 최대 5초 대기하면서 stdout 한 줄 읽기
    $task = $proc.StandardOutput.ReadLineAsync()
    if ($task.Wait(5000)) {
        $line = $task.Result
        Write-Host "  STDOUT: $line"
        try { $proc.Kill() } catch {}
        if ($line -match '"jsonrpc"') {
            return $true
        }
        Write-Host "  JSON-RPC 응답 형식 아님" -ForegroundColor Yellow
        return $false
    }
    # 응답 없으면 stderr 덤프
    try { $proc.Kill() } catch {}
    $errOut = $proc.StandardError.ReadToEnd()
    Write-Host "  5초 내 응답 없음. STDERR 덤프:" -ForegroundColor Yellow
    Write-Host $errOut
    return $false
}

# --- 12. 트레이의 Claude Desktop 잔류 프로세스 ---
Check "Claude Desktop 프로세스 상태" {
    $procs = Get-Process | Where-Object { $_.ProcessName -match "Claude" }
    if ($procs) {
        Write-Host "  실행 중인 Claude 프로세스:"
        $procs | ForEach-Object { Write-Host "    PID=$($_.Id) Name=$($_.ProcessName)" }
        Write-Host "  ★ config 수정 후 변경 안 먹으면 위 프로세스 전부 종료 후 재시작 필요" -ForegroundColor Yellow
    } else {
        Write-Host "  Claude Desktop 실행 중 아님 (config 수정 후 시작하면 됨)"
    }
    return $true
}

# --- 요약 ---
Write-Host ""
Write-Host "=== 요약 ===" -ForegroundColor Yellow
$results | Format-Table -AutoSize
Write-Host ""
if ($failed -gt 0) {
    Write-Host "FAIL: $failed 건. 위 빨간 메시지부터 해결." -ForegroundColor Red
    Write-Host ""
    Write-Host "가장 결정적인 단서: [서버 initialize 응답 스모크 테스트]의 STDERR 덤프." -ForegroundColor Yellow
} else {
    Write-Host "전부 OK. Claude Desktop 완전 재시작 후에도 -32000 나오면 stderr 로그(%APPDATA%\Claude\logs\) 확인." -ForegroundColor Green
}
