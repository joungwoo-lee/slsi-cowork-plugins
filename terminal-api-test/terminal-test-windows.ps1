$ErrorActionPreference = 'Stop'

# 사용 방법:
#   1. 로컬에서 게이트웨이 서버를 먼저 실행하여 http://127.0.0.1:18081 로 접속 가능해야 합니다.
#   2. curl.exe 와 websocat 을 설치합니다.
#   3. PowerShell 에서 이 스크립트를 실행합니다:
#        .\terminal-test-windows.ps1
#      또는 세션 제목을 직접 넣어 실행할 수 있습니다:
#        .\terminal-test-windows.ps1 "내 터미널 테스트"
#   4. websocat 이 연결되면 JSON 한 줄씩 붙여넣습니다:
#        {"action":"send","prompt":"안녕하세요. 제 이름은 준입니다. 기억해줘."}
#        {"action":"send","prompt":"내 이름이 뭐였지?"}
#   5. 다른 PowerShell 창에서 아래 명령으로 저장된 대화 이력을 확인할 수 있습니다:
#        curl.exe -s http://127.0.0.1:18081/api/sessions/<key>/history
#
# 선택 사항:
#   $env:BASE_URL = 'http://127.0.0.1:18081'
#   .\terminal-test-windows.ps1

# 환경 변수로 게이트웨이 주소를 덮어쓸 수 있게 합니다.
# 기본값은 로컬 Windows 게이트웨이 주소입니다.
$BaseUrl = if ($env:BASE_URL) { $env:BASE_URL } else { 'http://127.0.0.1:18081' }

# 첫 번째 인자가 있으면 세션 제목으로 사용합니다.
$Title = if ($args.Count -gt 0) { $args[0] } else { 'Terminal Test' }

# 필요한 명령이 없으면 설치 방법과 함께 즉시 실패시킵니다.
function Test-RequiredCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Hint
    )

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "필수 명령을 찾을 수 없습니다: $Name`n$Hint"
    }
}

# curl.exe 는 HTTP 세션 생성에 쓰고, websocat 은 대화용 WebSocket 연결에 씁니다.
Test-RequiredCommand -Name 'curl.exe' -Hint '설치 예시: winget 으로 curl 을 설치하거나 Git for Windows 를 설치하세요.'
Test-RequiredCommand -Name 'websocat' -Hint '설치 예시: winget install Rustlang.Rustup ; cargo install websocat'

Write-Host "세션을 생성합니다: $BaseUrl ..."

# REST API 로 새 게이트웨이 세션을 생성합니다.
# 응답 형태는 보통 {"key":"<8자리 세션 키>"} 입니다.
$response = curl.exe -fsS -X POST "$BaseUrl/api/sessions" -H "Content-Type: application/json" -d "{\"title\":\"$Title\"}"

# PowerShell 에서 JSON 을 파싱해 세션 key 를 꺼냅니다.
# 이 key 를 기준으로 게이트웨이가 같은 백엔드 대화 세션에 연결합니다.
$json = $response | ConvertFrom-Json
$key = $json.key

if (-not $key) {
    throw "응답에서 세션 key 를 파싱하지 못했습니다: $response"
}

# HTTP 기본 주소를 WebSocket 주소로 바꾸고 세션 경로를 붙입니다.
$wsUrl = $BaseUrl -replace '^http', 'ws'
$wsUrl = "$wsUrl/ws/$key"

Write-Host ''
Write-Host '세션이 생성되었습니다.'
Write-Host "  key: $key"
Write-Host "  ws : $wsUrl"
Write-Host "  history: $BaseUrl/api/sessions/$key/history"
Write-Host ''

# 첫 질문과 후속 질문을 바로 붙여넣어 테스트할 수 있도록 예시를 보여줍니다.
# 같은 key 로 계속 보내면 동일한 대화 흐름으로 이어집니다.
Write-Host 'WebSocket 연결 후 아래 JSON 을 한 줄씩 붙여넣으세요:'
Write-Host ''
Write-Host '{"action":"send","prompt":"안녕하세요. 제 이름은 준입니다. 기억해줘."}'
Write-Host '{"action":"send","prompt":"내 이름이 뭐였지?"}'
Write-Host ''
Write-Host '종료하려면 Ctrl+C 를 누르세요.'
Write-Host ''
Write-Host 'WebSocket 을 엽니다...'
Write-Host ''

# 이제 websocat 에 제어를 넘겨 터미널을 직접 WebSocket 클라이언트처럼 사용합니다.
# 여기서 입력한 JSON 한 줄은 게이트웨이로 전송되고, 받은 이벤트는 그대로 출력됩니다.
& websocat $wsUrl
