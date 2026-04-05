#!/bin/bash
set -euo pipefail

APP_DIR="$HOME/AnythingLLM"
TARGET_RAG_FOLDER="$HOME/my_rag_docs"
FIXED_API_KEY="my-secret-rag-key-2026"
DB_PATH="$HOME/.config/anythingllm-desktop/storage/anythingllm.db"

need_sudo() {
    if [ "$(id -u)" -ne 0 ]; then
        echo "sudo"
    fi
}

install_system_packages() {
    local SUDO
    SUDO="$(need_sudo)"

    echo ">>> 0. 시스템 패키지 확인 및 설치..."

    if command -v apt-get >/dev/null 2>&1; then
        $SUDO apt-get update
        $SUDO apt-get install -y libfuse2 sqlite3 curl
    elif command -v dnf >/dev/null 2>&1; then
        $SUDO dnf install -y fuse fuse-libs sqlite sqlite curl
    elif command -v yum >/dev/null 2>&1; then
        $SUDO yum install -y fuse fuse-libs sqlite sqlite curl
    elif command -v zypper >/dev/null 2>&1; then
        $SUDO zypper install -y fuse libfuse2 sqlite3 curl
    elif command -v pacman >/dev/null 2>&1; then
        $SUDO pacman -Sy --noconfirm fuse2 sqlite curl
    else
        echo "[ERROR] 지원되는 패키지 매니저를 찾지 못했습니다. libfuse.so.2 와 sqlite3를 수동 설치해 주세요." >&2
        exit 1
    fi
}

install_system_packages

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
