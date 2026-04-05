#!/bin/bash
set -euo pipefail

APP_DIR="$HOME/anythingllm-server"
TARGET_RAG_FOLDER="$HOME/my_rag_docs"
FIXED_API_KEY="my-secret-rag-key-2026"
DB_PATH="$APP_DIR/server/storage/anythingllm.db"

wait_for_http() {
  local url="$1"
  local max_tries="${2:-60}"
  local i=0
  while [ "$i" -lt "$max_tries" ]; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    i=$((i + 1))
    sleep 2
  done
  return 1
}

echo ">>> 1. 디렉토리 및 필수 패키지 확인..."
mkdir -p "$TARGET_RAG_FOLDER"
if ! command -v yarn >/dev/null 2>&1; then
    echo "yarn이 없습니다. npm install -g yarn 으로 설치합니다."
    npm install -g yarn
fi
if ! command -v sqlite3 >/dev/null 2>&1; then
    echo "[ERROR] sqlite3가 필요합니다. 먼저 설치해 주세요." >&2
    exit 1
fi
if ! command -v curl >/dev/null 2>&1; then
    echo "[ERROR] curl이 필요합니다. 먼저 설치해 주세요." >&2
    exit 1
fi
if ! command -v git >/dev/null 2>&1; then
    echo "[ERROR] git이 필요합니다. 먼저 설치해 주세요." >&2
    exit 1
fi
if ! command -v openssl >/dev/null 2>&1; then
    echo "[ERROR] openssl이 필요합니다. 먼저 설치해 주세요." >&2
    exit 1
fi

echo ">>> 2. AnythingLLM 소스 클론 (서버용)..."
if [ ! -d "$APP_DIR" ]; then
    git clone https://github.com/Mintplex-Labs/anything-llm.git "$APP_DIR"
fi

echo ">>> 3. 백엔드(Server) 패키지 설치..."
cd "$APP_DIR/server"
yarn install

echo ">>> 4. 서버 환경변수(.env) 자동 설정..."
cp .env.example .env
JWT_SECRET=$(openssl rand -hex 16)
sed -i "s/^JWT_SECRET=.*/JWT_SECRET='$JWT_SECRET'/" .env
sed -i "s/^# STORAGE_DIR=.*/STORAGE_DIR='\/home\/joungwoolee\/anythingllm-server\/server\/storage'/" .env

echo ">>> 5. 데이터베이스 마이그레이션 (초기화)..."
npx prisma generate
npx prisma migrate deploy

echo ">>> 6. 순수 API 서버 백그라운드 구동..."
nohup yarn start > "$APP_DIR/server/server.log" 2>&1 &
sleep 15

if ! wait_for_http "http://localhost:3001" 60; then
  echo "[ERROR] personal-rag 서버가 기동되지 않았습니다." >&2
  exit 1
fi

if [ ! -f "$DB_PATH" ]; then
  echo "[ERROR] DB 파일이 생성되지 않았습니다: $DB_PATH" >&2
  exit 1
fi

echo ">>> 7. 고정 API 키 직접 주입..."
sqlite3 "$DB_PATH" "INSERT OR IGNORE INTO api_keys (secret) VALUES ('$FIXED_API_KEY');"

echo ">>> 8. 'my_rag' 워크스페이스 자동 생성..."
curl -s -X POST http://localhost:3001/api/workspace/new \
     -H "Authorization: Bearer $FIXED_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"name": "my_rag"}' > /dev/null || true

echo "===================================================="
echo "✅ non-Docker personal-rag 셋업 완료"
echo "📂 RAG 문서 폴더: $TARGET_RAG_FOLDER"
echo "🌐 접속 주소: http://localhost:3001"
echo "🔑 고정 API 키: $FIXED_API_KEY"
echo "===================================================="
