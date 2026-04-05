#!/bin/bash
set -euo pipefail

APP_DIR="$HOME/personal-rag"
TARGET_RAG_FOLDER="$HOME/my_rag_docs"
STORAGE_DIR="$APP_DIR/storage"
FIXED_API_KEY="my-secret-rag-key-2026"
CONTAINER_NAME="personal-rag-server"
IMAGE_NAME="mintplexlabs/anythingllm:latest"
DB_PATH="$STORAGE_DIR/anythingllm.db"

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

echo ">>> 1. 디렉토리 준비..."
mkdir -p "$APP_DIR"
mkdir -p "$STORAGE_DIR"
mkdir -p "$TARGET_RAG_FOLDER"

echo ">>> 2. Docker / sqlite3 확인..."
if ! command -v docker >/dev/null 2>&1; then
    echo "[ERROR] docker가 필요합니다. 먼저 docker를 설치해 주세요." >&2
    exit 1
fi
if ! command -v sqlite3 >/dev/null 2>&1; then
    echo "[ERROR] sqlite3가 필요합니다. 먼저 sqlite3를 설치해 주세요." >&2
    exit 1
fi
if ! command -v curl >/dev/null 2>&1; then
    echo "[ERROR] curl이 필요합니다. 먼저 curl을 설치해 주세요." >&2
    exit 1
fi

echo ">>> 3. 이미지 준비..."
docker pull "$IMAGE_NAME"

echo ">>> 4. 기존 컨테이너 정리..."
if docker ps -a --format '{{.Names}}' | grep -Fxq "$CONTAINER_NAME"; then
    docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
fi

echo ">>> 5. 서버 컨테이너 실행..."
docker run -d \
  --name "$CONTAINER_NAME" \
  -p 3001:3001 \
  -e STORAGE_DIR=/app/server/storage \
  -v "$STORAGE_DIR:/app/server/storage" \
  "$IMAGE_NAME" >/dev/null

echo ">>> 6. 서버/DB 준비 대기..."
if ! wait_for_http "http://localhost:3001" 60; then
  echo "[ERROR] personal-rag 서버가 기동되지 않았습니다." >&2
  exit 1
fi

for _ in $(seq 1 60); do
  if [ -f "$DB_PATH" ]; then
    break
  fi
  sleep 2
done

if [ ! -f "$DB_PATH" ]; then
  echo "[ERROR] DB 파일이 생성되지 않았습니다: $DB_PATH" >&2
  exit 1
fi

echo ">>> 7. 고정 API 키 주입..."
sqlite3 "$DB_PATH" "INSERT OR IGNORE INTO api_keys (secret) VALUES ('$FIXED_API_KEY');"

echo ">>> 8. API 키 반영 확인..."
sqlite3 "$DB_PATH" "SELECT secret FROM api_keys WHERE secret = '$FIXED_API_KEY';" | grep -Fx "$FIXED_API_KEY" >/dev/null

echo "===================================================="
echo "✅ 서버형 personal-rag 셋업 완료"
echo "📂 문서 폴더: $TARGET_RAG_FOLDER"
echo "🗄️ 저장소 폴더: $STORAGE_DIR"
echo "🌐 접속 주소: http://localhost:3001"
echo "🔑 고정 API 키: $FIXED_API_KEY"
echo "===================================================="
