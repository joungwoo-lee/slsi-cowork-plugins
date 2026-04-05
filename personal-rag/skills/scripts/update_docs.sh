#!/bin/bash
set -euo pipefail

TARGET_RAG_FOLDER="$HOME/my_rag_docs"
FIXED_API_KEY="my-secret-rag-key-2026"
WORKSPACE_SLUG="my_rag"

echo ">>> 1. 폴더 내 파일들을 AnythingLLM에 업로드 중..."
shopt -s nullglob
for file in "$TARGET_RAG_FOLDER"/*; do
    if [ -f "$file" ]; then
        echo "업로드: $(basename "$file")"
        curl -X POST http://localhost:3001/api/document/upload \
             -H "Authorization: Bearer $FIXED_API_KEY" \
             -F "file=@$file" > /dev/null 2>&1
    fi
done

echo ">>> 2. 워크스페이스에 파일 연결 및 임베딩(벡터화) 업데이트..."
curl -X POST http://localhost:3001/api/workspace/$WORKSPACE_SLUG/update-embeddings \
     -H "Authorization: Bearer $FIXED_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"adds": ["custom-documents"], "deletes": []}'

echo "===================================================="
echo "✅ 임베딩 완료! 이제 클로드가 이 파일들을 읽을 수 있습니다."
echo "===================================================="
