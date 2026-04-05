#!/bin/bash
# setup_rag.sh - Adapted from integrated setup logic

set -euo pipefail

APP_DIR="$HOME/anythingllm-server"
TARGET_RAG_FOLDER="$HOME/my_rag_docs"
FIXED_API_KEY="my-secret-rag-key-2026"
DB_PATH="$APP_DIR/server/storage/anythingllm.db"

echo ">>> 1. 필수 패키지 설치 (Node.js, Yarn, Python, jq, sqlite3 등)..."
# Note: Using sudo if not root, assuming environment allows or asks for it.
# In OpenClaw, exec might need permission.
sudo apt-get update -y
sudo apt-get install -y curl git sqlite3 python3 make g++ psmisc jq

if ! command -v node &> /dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    sudo apt-get install -y nodejs
fi
if ! command -v yarn &> /dev/null; then
    sudo npm install -g yarn
fi

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
sleep 5 # 콜렉터 예열 대기

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
