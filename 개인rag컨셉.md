완벽한 **"설치 ➔ 파일 투척 ➔ 클로드 스킬 호출"** 파이프라인을 완성해 드립니다.
말씀하신 흐름이 끊기지 않도록, 초기 셋업 시 **'Workspace(지식 베이스)'까지 API로 자동 생성**하고, 파일을 폴더에 넣은 뒤 **임베딩(벡터화)을 자동화하는 스크립트**까지 추가했습니다.
### 1단계: 셋업 실행 (환경 구성 및 워크스페이스 자동 생성)
이 스크립트(setup_rag.sh)를 실행하면 AnythingLLM 다운로드, API 고정키 삽입, 서버 구동에 이어 **'클로드가 검색할 전용 워크스페이스'까지 자동으로 생성**합니다.
```bash
#!/bin/bash

APP_DIR="$HOME/AnythingLLM"
TARGET_RAG_FOLDER="$HOME/my_rag_docs"
FIXED_API_KEY="my-secret-rag-key-2026"
DB_PATH="$HOME/.config/anythingllm-desktop/storage/anythingllm.db"

echo ">>> 1. 디렉토리 및 파일 준비..."
mkdir -p "$APP_DIR"
mkdir -p "$TARGET_RAG_FOLDER"
cd "$APP_DIR" || exit

echo ">>> 2. AppImage 다운로드..."
if [ ! -f "AnythingLLM.AppImage" ]; then
    curl -L https://cdn.anythingllm.com/latest/AnythingLLMDesktop.AppImage -o AnythingLLM.AppImage
    chmod +x AnythingLLM.AppImage
fi

echo ">>> 3. DB 초기화를 위한 임시 구동..."
./AnythingLLM.AppImage --no-sandbox & 
APP_PID=$!
sleep 12 # DB 생성 대기
kill $APP_PID
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

```
### 2단계: 문서 투척 및 임베딩 (데이터 업데이트)
~/my_rag_docs 폴더에 워드, PDF, 코드 파일 등을 마음껏 복사해 넣습니다.
파일을 넣은 후, AI가 이를 검색할 수 있도록 벡터 DB에 밀어 넣는(Embedding) 스크립트(update_docs.sh)를 실행합니다.
```bash
#!/bin/bash
# update_docs.sh : 폴더의 파일들을 AnythingLLM에 업로드하고 임베딩합니다.

TARGET_RAG_FOLDER="$HOME/my_rag_docs"
FIXED_API_KEY="my-secret-rag-key-2026"
WORKSPACE_SLUG="my_rag" # 셋업에서 만든 워크스페이스 이름

echo ">>> 1. 폴더 내 파일들을 AnythingLLM에 업로드 중..."
for file in "$TARGET_RAG_FOLDER"/*; do
    if [ -f "$file" ]; then
        echo "업로드: $(basename "$file")"
        curl -X POST http://localhost:3001/api/document/upload \
             -H "Authorization: Bearer $FIXED_API_KEY" \
             -F "file=@$file" > /dev/null 2>&1
    fi
done

echo ">>> 2. 워크스페이스에 파일 연결 및 임베딩(벡터화) 업데이트..."
# 업로드된 문서들을 my_rag 워크스페이스에 매핑하고 임베딩을 트리거합니다.
curl -X POST http://localhost:3001/api/workspace/$WORKSPACE_SLUG/update-embeddings \
     -H "Authorization: Bearer $FIXED_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"adds": ["custom-documents"], "deletes": []}'

echo "===================================================="
echo "✅ 임베딩 완료! 이제 클로드가 이 파일들을 읽을 수 있습니다."
echo "===================================================="

```
### 3단계: 클로드 연동 및 스킬 호출 (준비 완료)
**1. 클로드 설정 파일(~/.config/Claude/claude_desktop_config.json)에 스킬 등록:**
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
이제 클로드에게 자연스럽게 명령만 하면 됩니다.
> **사용자:** "AnythingLLM 스킬 사용해서 my_rag 워크스페이스 검색해 줘. 방금 내가 넣은 문서들 바탕으로 우리 프로젝트의 인증 API 엔드포인트들을 표로 정리해."
> 
> **클로드 (동작 흐름):**
>  1. 🛠️ *도구 사용 중: query_workspace (대상: my_rag, 검색어: 인증 API 엔드포인트)*
>  2. (AnythingLLM 로컬 서버에서 관련된 문서 내용만 즉시 발췌해서 클로드에게 전달)
>  3. **클로드 답변:** "검색된 문서를 바탕으로 인증 API를 정리해 드립니다. 로그인 엔드포인트는..."
> 
이렇게 구성하시면, **~/my_rag_docs에 파일 복사 ➔ update_docs.sh 실행 ➔ 클로드에 질문** 이라는 완벽하고 독립적인 로컬 RAG 파이프라인이 완성됩니다.
