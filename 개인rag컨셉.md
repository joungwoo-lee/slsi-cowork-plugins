완벽한 **"설치 ➔ 파일 투척 ➔ 클로드 스킬 호출"** 파이프라인을 완성해 드립니다.
말씀하신 흐름이 끊기지 않도록, 초기 셋업 시 **'Workspace(지식 베이스)'까지 API로 자동 생성**하고, 파일을 폴더에 넣은 뒤 **임베딩(벡터화)을 자동화하는 스크립트**까지 추가했습니다.

이번 구성은 더 이상 데스크톱 AppImage를 전제로 하지 않고, **`개인rag서버용.md`의 순수 헤드리스 서버 방식**을 기준으로 합니다.
즉, Docker 없이 **AnythingLLM 소스를 직접 받아 백엔드만 구동하는 서버형(non-Docker, headless backend)** 흐름으로 정리합니다.

### 1단계: 셋업 실행 (환경 구성 및 워크스페이스 자동 생성)
이 스크립트(`setup_server_rag.sh`)를 실행하면 AnythingLLM 소스를 클론하고, 백엔드만 설치/초기화한 뒤, **고정 API 키 주입 + `my_rag` 워크스페이스 자동 생성**까지 처리합니다.

```bash
#!/bin/bash

APP_DIR="$HOME/anythingllm-server"
TARGET_RAG_FOLDER="$HOME/my_rag_docs"
FIXED_API_KEY="my-secret-rag-key-2026"
DB_PATH="$APP_DIR/server/storage/anythingllm.db"

echo ">>> 1. 디렉토리 및 필수 패키지 확인..."
mkdir -p "$TARGET_RAG_FOLDER"
if ! command -v yarn &> /dev/null; then
    echo "yarn이 없습니다. npm install -g yarn 으로 먼저 설치해주세요."
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
sed -i "s/^STORAGE_DIR=.*/STORAGE_DIR='\/storage'/" .env

echo ">>> 5. 데이터베이스 마이그레이션 (초기화)..."
npx prisma generate
npx prisma migrate deploy

echo ">>> 6. 순수 API 서버 백그라운드 구동..."
nohup yarn start > "$APP_DIR/server/server.log" 2>&1 &
SERVER_PID=$!
echo "서버 부팅 대기 중 (15초)..."
sleep 15

echo ">>> 7. 고정 API 키 직접 주입..."
sqlite3 "$DB_PATH" "INSERT OR IGNORE INTO api_keys (secret) VALUES ('$FIXED_API_KEY');"

echo ">>> 8. 'my_rag' 워크스페이스 자동 생성..."
curl -s -X POST http://localhost:3001/api/workspace/new \
     -H "Authorization: Bearer $FIXED_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"name": "my_rag"}' > /dev/null

echo "===================================================="
echo "✅ 서버용 API 셋업 완료! (포트: 3001)"
echo "📂 RAG 문서 투척 폴더: $TARGET_RAG_FOLDER"
echo "===================================================="
```

### 2단계: 문서 투척 및 임베딩 (데이터 업데이트)
`~/my_rag_docs` 폴더에 워드, PDF, 코드 파일 등을 복사해 넣습니다.
파일을 넣은 후, AI가 이를 검색할 수 있도록 벡터 DB에 반영하는 `update_docs.sh`를 실행합니다.

```bash
#!/bin/bash

TARGET_RAG_FOLDER="$HOME/my_rag_docs"
FIXED_API_KEY="my-secret-rag-key-2026"
WORKSPACE_SLUG="my_rag"

echo ">>> 폴더 내 문서 업로드 및 임베딩 진행 중..."
for file in "$TARGET_RAG_FOLDER"/*; do
    if [ -f "$file" ]; then
        curl -s -X POST http://localhost:3001/api/document/upload \
             -H "Authorization: Bearer $FIXED_API_KEY" \
             -F "file=@$file" > /dev/null
    fi
done

curl -s -X POST http://localhost:3001/api/workspace/$WORKSPACE_SLUG/update-embeddings \
     -H "Authorization: Bearer $FIXED_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"adds": ["custom-documents"], "deletes": []}' > /dev/null

echo "✅ 임베딩 완료. 이제 클로드 스킬을 사용할 수 있습니다."
```

### 3단계: 클로드 연동 및 스킬 호출 (준비 완료)
**1. 클로드 설정 파일(`~/.config/Claude/claude_desktop_config.json`)에 MCP 등록:**

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

**2. 클로드 재시작 후 채팅창에서 스킬 호출:**
이제 클로드에게 자연스럽게 명령하면 됩니다.

> **사용자:** "AnythingLLM 스킬 사용해서 my_rag 워크스페이스 검색해 줘. 방금 내가 넣은 문서들 바탕으로 우리 프로젝트의 인증 API 엔드포인트들을 정리해."
>
> **클로드 (동작 흐름):**
> 1. `my_rag` 워크스페이스를 질의
> 2. AnythingLLM 로컬 서버가 관련 문서 내용을 반환
> 3. 검색 결과를 기반으로 답변 생성

이렇게 구성하시면, **`~/my_rag_docs`에 파일 복사 ➔ `update_docs.sh` 실행 ➔ 클로드에 질문** 이라는 완벽하고 독립적인 **non-Docker 서버형 로컬 RAG 파이프라인**이 완성됩니다.
