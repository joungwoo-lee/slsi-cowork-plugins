#!/bin/bash
# setup_rag.sh - Headless AnythingLLM setup (no sudo)

set -euo pipefail

APP_DIR="$HOME/anythingllm-server"
TARGET_RAG_FOLDER="$HOME/my_rag_docs"
FIXED_API_KEY="my-secret-rag-key-2026"
DB_PATH="$APP_DIR/server/storage/anythingllm.db"

if [ "${EUID:-$(id -u)}" -eq 0 ]; then
    SUDO=()
else
    if ! command -v sudo &> /dev/null; then
        echo "sudo가 없어서 시스템 패키지 설치를 진행할 수 없습니다. root로 실행하거나 sudo를 먼저 설치해 주세요." >&2
        exit 1
    fi
    SUDO=(sudo)
fi

run_as_root() {
    "${SUDO[@]}" "$@"
}

ensure_system_pkg() {
    local cmd="$1" pkg="$2"
    if command -v "$cmd" &> /dev/null; then
        return 0
    fi

    echo ">>> '$cmd' 명령이 없어서 '$pkg' 설치를 시도합니다..."
    run_as_root apt-get install -y "$pkg"

    if ! command -v "$cmd" &> /dev/null; then
        echo "❌ '$pkg' 설치 후에도 '$cmd' 명령을 찾을 수 없습니다." >&2
        exit 1
    fi
}

ensure_yarn() {
    if command -v yarn &> /dev/null; then
        return 0
    fi

    echo ">>> yarn이 없습니다. 전역 설치를 시도합니다..."
    if command -v corepack &> /dev/null; then
        run_as_root corepack enable || true
    fi
    run_as_root npm install -g yarn

    if ! command -v yarn &> /dev/null; then
        echo "❌ yarn 설치 후에도 명령을 찾을 수 없습니다." >&2
        exit 1
    fi
}

echo ">>> 1. 필수 패키지 설치/확인..."
run_as_root apt-get update -y
run_as_root apt-get install -y curl git sqlite3 python3 make g++ psmisc jq openssl

ensure_system_pkg curl curl
ensure_system_pkg git git
ensure_system_pkg sqlite3 sqlite3
ensure_system_pkg python3 python3
ensure_system_pkg jq jq
ensure_system_pkg openssl openssl
ensure_system_pkg make make

if ! command -v node &> /dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | run_as_root bash -
    run_as_root apt-get install -y nodejs
fi

ensure_system_pkg node nodejs

ensure_yarn

echo ">>> 2. AnythingLLM 소스 클론 (기존 찌꺼기 제거)..."
rm -rf "$APP_DIR"
git clone https://github.com/Mintplex-Labs/anything-llm.git "$APP_DIR"
mkdir -p "$TARGET_RAG_FOLDER"

echo ">>> 3. 콜렉터(Collector) 서버 셋업 및 구동 (포트 8888)..."
cd "$APP_DIR/collector"
yarn install
cp .env.example .env
echo "STORAGE_DIR='$APP_DIR/server/storage'" >> .env
nohup yarn start > collector.log 2>&1 &
sleep 5

echo ">>> 4. API 백엔드 서버 셋업 (포트 3001)..."
cd "$APP_DIR/server"
yarn install
cp .env.example .env
JWT_SECRET=$(openssl rand -hex 16)
sed -i "s/^JWT_SECRET=.*/JWT_SECRET='$JWT_SECRET'/" .env
sed -i "s|^STORAGE_DIR=.*|STORAGE_DIR='$APP_DIR/server/storage'|" .env

echo ">>> 5. 데이터베이스(SQLite) 초기화..."
npx prisma generate
npx prisma migrate deploy

echo ">>> 6. API 서버 구동..."
nohup yarn start > server.log 2>&1 &
echo "서버 부팅 대기 중 (15초)..."
sleep 15

echo ">>> 7. 고정 API 키 주입 및 워크스페이스 생성..."
sqlite3 "$DB_PATH" "INSERT OR IGNORE INTO api_keys (secret) VALUES ('$FIXED_API_KEY');"

curl -s -X POST http://localhost:3001/api/v1/workspace/new \
     -H "Authorization: Bearer $FIXED_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"name": "my_rag"}' > /dev/null

echo "===================================================="
echo "✅ 서버 셋업 완료! (API: 3001, Collector: 8888)"
echo "📂 RAG 폴더: $TARGET_RAG_FOLDER"
echo "🔑 API Key: $FIXED_API_KEY"
echo "===================================================="
