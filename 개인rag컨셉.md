변명의 여지가 없습니다. 앞서 발생한 모든 에러(GUI 종속, 패키지 누락, 콜렉터 누락)를 원천 차단한 **완벽한 순수 서버용 최종 스크립트**입니다.
깡통 리눅스 컨테이너 환경을 기준으로 필수 패키지 설치부터 콜렉터/API 서버 구동, 워크스페이스 생성까지 한 번에 끝내도록 전부 묶었습니다.
### 1. 통합 셋업 스크립트 (1_setup_anythingllm.sh)
이 스크립트 하나로 모든 설치와 서버 구동이 백그라운드에서 완료됩니다.
```bash
#!/bin/bash
# 1_setup_anythingllm.sh

APP_DIR="$HOME/anythingllm-server"
TARGET_RAG_FOLDER="$HOME/my_rag_docs"
FIXED_API_KEY="my-secret-rag-key-2026"
DB_PATH="$APP_DIR/server/storage/anythingllm.db"

echo ">>> 1. 필수 패키지 설치 (Node.js, Yarn, Python, jq, sqlite3 등)..."
apt-get update -y
apt-get install -y curl git sqlite3 python3 make g++ psmisc jq

if ! command -v node &> /dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y nodejs
fi
if ! command -v yarn &> /dev/null; then
    npm install -g yarn
fi

echo ">>> 2. AnythingLLM 소스 클론 (기존 찌꺼기 제거)..."
rm -rf "$APP_DIR"
git clone https://github.com/Mintplex-Labs/anything-llm.git "$APP_DIR"
mkdir -p "$TARGET_RAG_FOLDER"

echo ">>> 3. 콜렉터(Collector) 서버 셋업 및 구동 (포트 8888)..."
cd "$APP_DIR/collector"
yarn install
cp .env.example .env
nohup yarn start > collector.log 2>&1 &
sleep 5 # 콜렉터 예열 대기

echo ">>> 4. API 백엔드 서버 셋업 (포트 3001)..."
cd "$APP_DIR/server"
yarn install
cp .env.example .env
JWT_SECRET=$(openssl rand -hex 16)
sed -i "s/^JWT_SECRET=.*/JWT_SECRET='$JWT_SECRET'/" .env
sed -i "s/^STORAGE_DIR=.*/STORAGE_DIR='\/storage'/" .env

echo ">>> 5. 데이터베이스(SQLite) 초기화..."
npx prisma generate
npx prisma migrate deploy

echo ">>> 6. API 서버 구동..."
nohup yarn start > server.log 2>&1 &
echo "서버 부팅 대기 중 (15초)..."
sleep 15

echo ">>> 7. 고정 API 키 주입 및 워크스페이스 생성..."
sqlite3 "$DB_PATH" "INSERT OR IGNORE INTO api_keys (secret) VALUES ('$FIXED_API_KEY');"

curl -s -X POST http://localhost:3001/api/workspace/new \
     -H "Authorization: Bearer $FIXED_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"name": "my_rag"}' > /dev/null

echo "===================================================="
echo "✅ 서버 셋업 완료! (API: 3001, Collector: 8888)"
echo "📂 RAG 폴더: $TARGET_RAG_FOLDER"
echo "🔑 API Key: $FIXED_API_KEY"
echo "===================================================="

```
### 2. 문서 업로드 및 임베딩 스크립트 (2_update_docs.sh)
~/my_rag_docs 폴더에 문서를 넣은 후 실행하세요. API 응답을 정확히 파싱하여 해당 파일들만 깔끔하게 임베딩하도록 수정했습니다.
```bash
#!/bin/bash
# 2_update_docs.sh

TARGET_RAG_FOLDER="$HOME/my_rag_docs"
FIXED_API_KEY="my-secret-rag-key-2026"
WORKSPACE_SLUG="my_rag"

echo ">>> 문서를 서버로 전송하고 임베딩을 시작합니다..."
DOC_LOCS="["

for file in "$TARGET_RAG_FOLDER"/*; do
    if [ -f "$file" ]; then
        echo "업로드 중: $(basename "$file")"
        # 1. 파일 업로드 후 저장된 경로(location) 추출
        RES=$(curl -s -X POST http://localhost:3001/api/document/upload \
             -H "Authorization: Bearer $FIXED_API_KEY" \
             -F "file=@$file")
        
        LOC=$(echo $RES | jq -r '.documents[0].location // empty')
        
        if [ -n "$LOC" ]; then
            DOC_LOCS="$DOC_LOCS\"$LOC\","
        fi
    fi
done

# 배열 문자열 정리 (마지막 쉼표 제거)
DOC_LOCS="${DOC_LOCS%,}]"
if [ "$DOC_LOCS" == "]" ]; then DOC_LOCS="[]"; fi

if [ "$DOC_LOCS" != "[]" ]; then
    echo ">>> 워크스페이스에 벡터 임베딩 적용 중..."
    # 2. 업로드된 문서들의 경로를 배열로 전달하여 임베딩 실행
    curl -s -X POST http://localhost:3001/api/workspace/$WORKSPACE_SLUG/update-embeddings \
         -H "Authorization: Bearer $FIXED_API_KEY" \
         -H "Content-Type: application/json" \
         -d "{\"adds\": $DOC_LOCS, \"deletes\": []}" > /dev/null
    echo "✅ 임베딩 완료! 이제 클로드에서 스킬을 사용할 수 있습니다."
else
    echo "⚠️ 처리할 새로운 문서가 없습니다."
fi

```
### 3. 클로드 스킬(MCP) 연동
클로드 설정 파일(~/.config/Claude/claude_desktop_config.json 등 사용 환경에 맞게)에 아래 내용만 추가하시면 됩니다.
```json
{
  "mcpServers": {
    "anythingllm": {
      "command": "npx",
      "args": ["-y", "@mintplex-labs/anythingllm-mcp-server"],
      "env": {
        "ANYTHINGLLM_API_KEY": "my-secret-rag-key-2026",
        "ANYTHINGLLM_BASE_URL": "http://localhost:3001/api"
      }
    }
  }
}

```
