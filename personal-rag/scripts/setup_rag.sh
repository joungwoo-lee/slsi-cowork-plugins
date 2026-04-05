#!/bin/bash
set -euo pipefail

APP_DIR="$HOME/AnythingLLM"
TARGET_RAG_FOLDER="$HOME/my_rag_docs"
FIXED_API_KEY="my-secret-rag-key-2026"
DB_PATH="$HOME/.config/anythingllm-desktop/storage/anythingllm.db"

echo ">>> 1. 디렉토리 및 파일 준비..."
mkdir -p "$APP_DIR"
mkdir -p "$TARGET_RAG_FOLDER"
cd "$APP_DIR"

echo ">>> 2. AppImage 다운로드..."
if [ ! -f "AnythingLLM.AppImage" ]; then
    curl -L https://cdn.anythingllm.com/latest/AnythingLLMDesktop.AppImage -o AnythingLLM.AppImage
    chmod +x AnythingLLM.AppImage
fi

echo ">>> 3. DB 초기화를 위한 임시 구동..."
./AnythingLLM.AppImage --no-sandbox &
APP_PID=$!
sleep 12
kill "$APP_PID" || true
sleep 2

echo ">>> 4. 고정 API 키 강제 주입..."
sqlite3 "$DB_PATH" "INSERT OR IGNORE INTO api_keys (secret) VALUES ('$FIXED_API_KEY');"

echo ">>> 5. 백그라운드 서버 구동..."
nohup ./AnythingLLM.AppImage --no-sandbox > anythingllm.log 2>&1 &

echo ">>> 6. 서버 로딩 대기 (API 활성화 대기)..."
sleep 15

echo ">>> 7. 'my_rag' 워크스페이스 자동 생성 (API 호출)..."
curl -X POST http://localhost:3001/api/workspace/new \
     -H "Authorization: Bearer $FIXED_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"name": "my_rag"}'

echo "===================================================="
echo "✅ 셋업 완료! AnythingLLM 스킬 준비 완료."
echo "📂 RAG 폴더: $TARGET_RAG_FOLDER"
echo "===================================================="
