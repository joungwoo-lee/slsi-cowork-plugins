#!/bin/bash
# setup_rag.sh - Headless AnythingLLM setup (no sudo)

set -euo pipefail

APP_DIR="$HOME/anythingllm-server"
TARGET_RAG_FOLDER="$HOME/my_rag_docs"
FIXED_API_KEY="my-secret-rag-key-2026"
DB_PATH="$APP_DIR/server/storage/anythingllm.db"

# ---------------------------------------------------------------------------
# Helper: check if a system package is available; warn if missing
# ---------------------------------------------------------------------------
check_pkg() {
    local cmd="$1" pkg="$2"
    if ! command -v "$cmd" &> /dev/null; then
        echo ""
        echo "⚠️  '$cmd' 명령을 찾을 수 없습니다."
        echo "   시스템 패키지 설치가 필요합니다: $pkg"
        echo "   root 또는 sudo 권한을 가진 사용자가 다음을 실행하세요:"
        echo "   → apt-get install -y $pkg"
        echo ""
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Helper: install npm global package without sudo (via prefix)
# ---------------------------------------------------------------------------
ensure_yarn() {
    if command -v yarn &> /dev/null; then return 0; fi
    echo ">>> yarn이 없습니다. npm prefix 방식으로 로컬 설치합니다..."
    npm install -g yarn --prefix "$HOME/.npm-global" 2>/dev/null || {
        echo ""
        echo "⚠️  yarn 설치 실패. 다음 중 하나를 시도하세요:"
        echo "   1) root 권한 있을 때: npm install -g yarn"
        echo "   2) nvm 사용 중이라면: nvm use <version> 후 npm install -g yarn"
        echo "   3) corepack 활성화: corepack enable"
        echo ""
        exit 1
    }
    export PATH="$HOME/.npm-global/bin:$PATH"
}

echo ">>> 1. 필수 명령어 확인..."
MISSING=0
check_pkg curl   curl    || MISSING=1
check_pkg git    git     || MISSING=1
check_pkg sqlite3 sqlite3 || MISSING=1
check_pkg python3 python3 || MISSING=1
check_pkg jq     jq      || MISSING=1
check_pkg openssl openssl || MISSING=1
check_pkg make   make    || MISSING=1

if [ "$MISSING" -eq 1 ]; then
    echo "❌ 누락된 패키지가 있습니다. 위 안내를 따라 설치 후 다시 실행하세요."
    exit 1
fi

check_pkg node nodejs || {
    echo "   Node.js 설치 방법 (권한 없이):"
    echo "   → nvm 사용: curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash"
    echo "      그 후: nvm install 20 && nvm use 20"
    exit 1
}

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
