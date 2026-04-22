#!/usr/bin/env bash

# 사용 방법:
#   1. 로컬에서 게이트웨이 서버를 먼저 실행하여 http://127.0.0.1:18081 로 접속 가능해야 합니다.
#   2. curl, websocat, python3 를 설치합니다.
#   3. 이 스크립트를 실행합니다:
#        ./terminal-test-linux.sh
#      또는 세션 제목을 직접 넣어 실행할 수 있습니다:
#        ./terminal-test-linux.sh "내 터미널 테스트"
#   4. websocat 이 연결되면 JSON 한 줄씩 붙여넣습니다:
#        {"action":"send","prompt":"안녕하세요. 제 이름은 준입니다. 기억해줘."}
#        {"action":"send","prompt":"내 이름이 뭐였지?"}
#   5. 다른 터미널에서 아래 명령으로 저장된 대화 이력을 확인할 수 있습니다:
#        curl -s http://127.0.0.1:18081/api/sessions/<key>/history
#
# 선택 사항:
#   BASE_URL=http://127.0.0.1:18081 ./terminal-test-linux.sh

# 오류, 미정의 변수, 파이프라인 실패가 발생하면 즉시 종료합니다.
# 중간에 잘못된 세션 키로 계속 진행하는 상황을 막기 위한 설정입니다.
set -euo pipefail

# 환경 변수로 게이트웨이 주소를 덮어쓸 수 있게 합니다.
# 기본값은 로컬 aiohttp 게이트웨이 주소입니다.
BASE_URL="${BASE_URL:-http://127.0.0.1:18081}"

# 첫 번째 인자가 있으면 세션 제목으로 사용합니다.
TITLE="${1:-Terminal Test}"

# 필요한 명령이 없으면 설치 방법과 함께 즉시 실패시킵니다.
require_cmd() {
  local cmd="$1"
  local hint="$2"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    printf '필수 명령을 찾을 수 없습니다: %s\n%s\n' "$cmd" "$hint" >&2
    exit 1
  fi
}

# curl 은 HTTP 세션 생성에 쓰고, websocat 은 대화용 WebSocket 연결에 쓰며,
# python3 는 curl 응답 JSON 에서 세션 key 를 안전하게 꺼내는 데만 사용합니다.
require_cmd curl "설치 예시: sudo apt update && sudo apt install -y curl"
require_cmd websocat "설치 예시: sudo snap install websocat 또는 cargo install websocat"
require_cmd python3 "설치 예시: sudo apt update && sudo apt install -y python3"

printf '세션을 생성합니다: %s ...\n' "$BASE_URL"

# REST API 로 새 게이트웨이 세션을 생성합니다.
# 응답 형태는 보통 {"key":"<8자리 세션 키>"} 입니다.
response="$(curl -fsS -X POST "$BASE_URL/api/sessions" -H "Content-Type: application/json" -d "{\"title\":\"$TITLE\"}")"

# 응답 JSON 에서 게이트웨이 세션 key 를 꺼냅니다.
# 이 key 를 기준으로 서버가 같은 OpenCode 대화 세션에 매핑합니다.
key="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["key"])' "$response")"

# http://host:port 를 ws://host:port 로 바꾸고 세션 WebSocket 경로를 붙입니다.
ws_url="${BASE_URL/http:/ws:}/ws/$key"

printf '\n세션이 생성되었습니다.\n'
printf '  key: %s\n' "$key"
printf '  ws : %s\n' "$ws_url"
printf '  history: %s/api/sessions/%s/history\n\n' "$BASE_URL" "$key"

# 첫 질문과 후속 질문을 바로 붙여넣어 테스트할 수 있도록 예시를 보여줍니다.
# 같은 key 로 계속 보내면 동일한 대화 흐름으로 이어집니다.
cat <<'EOF'
WebSocket 연결 후 아래 JSON 을 한 줄씩 붙여넣으세요:

{"action":"send","prompt":"안녕하세요. 제 이름은 준입니다. 기억해줘."}
{"action":"send","prompt":"내 이름이 뭐였지?"}

종료하려면 Ctrl+C 를 누르세요.
EOF

printf '\nWebSocket 을 엽니다...\n\n'

# 현재 셸 프로세스를 websocat 으로 교체합니다.
# 이후 터미널에 입력한 JSON 한 줄은 그대로 게이트웨이로 전송되고,
# 게이트웨이가 보내는 JSON 이벤트는 터미널에 그대로 출력됩니다.
exec websocat "$ws_url"
