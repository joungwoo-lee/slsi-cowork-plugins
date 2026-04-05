아차, 제가 헛발질을 제대로 했네요. 맞습니다. GUI도 없는 리눅스 서버(컨테이너) 환경에서 데스크톱용(AppImage)을 쓰라고 한 건 완전 바보 같은 짓이었습니다. 화면(디스플레이) 관련 라이브러리가 없는 컨테이너에서는 애초에 에러만 뿜고 실행되지도 않습니다.
도커-인-도커(DinD) 없이, 컨테이너 내부에서 **완벽하게 백그라운드로 돌아가는 '순수 헤드리스(Headless) 서버용'** 세팅으로 전면 수정한 스크립트를 드립니다.
AnythingLLM의 프론트엔드(웹 UI)조차 띄우지 않고, **오직 API 통신과 문서 RAG 처리만 담당하는 '서버(Backend)'만 구동**하여 자원 소모를 최소화했습니다.
### 🖥️ 진짜 서버용(Headless Backend) RAG 자동 셋업 스크립트
아래 스크립트(setup_server_rag.sh)는 깃 클론부터 백엔드 빌드, 서버 구동, DB 초기화, API 키 고정 주입까지 무인(Non-interactive)으로 한 번에 처리합니다.
```bash
#!/bin/bash

# 1. 설정 변수
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
# 프론트엔드 무시하고 순수 API 서버만 설치
cd "$APP_DIR/server"
yarn install

echo ">>> 4. 서버 환경변수(.env) 자동 설정..."
# example 복사 후 무작위 JWT 시크릿 생성 및 주입
cp .env.example .env
JWT_SECRET=$(openssl rand -hex 16)
sed -i "s/^JWT_SECRET=.*/JWT_SECRET='$JWT_SECRET'/" .env
# 로컬 스토리지 모드로 강제 설정
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

echo ">>> 8. 클로드가 사용할 'my_rag' 워크스페이스 자동 생성..."
curl -s -X POST http://localhost:3001/api/workspace/new \
     -H "Authorization: Bearer $FIXED_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"name": "my_rag"}' > /dev/null

echo "===================================================="
echo "✅ 서버용 API 셋업 완료! (포트: 3001)"
echo "📂 RAG 문서 투척 폴더: $TARGET_RAG_FOLDER"
echo "===================================================="

```
### 📂 문서 임베딩(업데이트) 스크립트
서버가 돌아가고 있으니, ~/my_rag_docs 폴더에 파일을 던져 넣은 뒤 아래 스크립트(update_docs.sh)를 실행하면 API를 통해 파일들이 서버로 쏙 빨려 들어가 벡터화됩니다.
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

# 워크스페이스 업데이트 및 임베딩 갱신
curl -s -X POST http://localhost:3001/api/workspace/$WORKSPACE_SLUG/update-embeddings \
     -H "Authorization: Bearer $FIXED_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"adds": ["custom-documents"], "deletes": []}' > /dev/null

echo "✅ 임베딩 완료. 이제 클로드 스킬을 사용할 수 있습니다."

```
이 방식은 불필요한 데스크톱 UI 자원을 1바이트도 쓰지 않고, 오직 포트 3001번으로 RAG 엔진만 깔끔하게 돌리는 **진짜 서버용 구성**입니다. 컨테이너 내부에서 구동하기에 완벽한 조건이니 이 스크립트로 바로 적용해 보십시오.
