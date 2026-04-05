#!/bin/bash
set -euo pipefail

APP_DIR="$HOME/personal-rag"
TARGET_RAG_FOLDER="$HOME/my_rag_docs"
STORAGE_DIR="$APP_DIR/storage"
FIXED_API_KEY="my-secret-rag-key-2026"
CONTAINER_NAME="personal-rag-server"
IMAGE_NAME="mintplexlabs/anythingllm:latest"

echo ">>> 1. 디렉토리 준비..."
mkdir -p "$APP_DIR"
mkdir -p "$STORAGE_DIR"
mkdir -p "$TARGET_RAG_FOLDER"

echo ">>> 2. Docker 확인..."
if ! command -v docker >/dev/null 2>&1; then
    echo "[ERROR] docker가 필요합니다. 먼저 docker를 설치해 주세요." >&2
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
  "$IMAGE_NAME"

echo ">>> 6. 서버 기동 대기..."
sleep 20

echo ">>> 7. API 키 준비 안내..."
echo "AnythingLLM docker 배포는 초기 관리자 설정을 통해 API 키를 발급하는 방식일 수 있습니다."
echo "브라우저에서 http://localhost:3001 접속 후 관리자 설정을 완료해 주세요."
echo "고정 키 사용이 꼭 필요하면 별도 API 생성 절차를 거쳐야 합니다."

echo "===================================================="
echo "✅ 서버형 personal-rag 기본 셋업 완료"
echo "📂 문서 폴더: $TARGET_RAG_FOLDER"
echo "🗄️ 저장소 폴더: $STORAGE_DIR"
echo "🌐 접속 주소: http://localhost:3001"
echo "===================================================="
