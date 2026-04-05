#!/bin/bash
# update_docs.sh - Adapted from integrated update logic

set -euo pipefail

TARGET_RAG_FOLDER="$HOME/my_rag_docs"
FIXED_API_KEY="my-secret-rag-key-2026"
WORKSPACE_SLUG="my_rag"

echo ">>> 문서를 서버로 전송하고 임베딩을 시작합니다..."
DOC_LOCS="["

shopt -s nullglob
for file in "$TARGET_RAG_FOLDER"/*; do
    if [ -f "$file" ]; then
        echo "업로드 중: $(basename "$file")"
        # 1. 파일 업로드 후 저장된 경로(location) 추출
        RES=$(curl -s -X POST http://localhost:3001/api/v1/document/upload \
             -H "Authorization: Bearer $FIXED_API_KEY" \
             -F "file=@$file")
        
        LOC=$(echo "$RES" | jq -r '.documents[0].location // empty')
        
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
    curl -s -X POST http://localhost:3001/api/v1/workspace/$WORKSPACE_SLUG/update-embeddings \
         -H "Authorization: Bearer $FIXED_API_KEY" \
         -H "Content-Type: application/json" \
         -d "{\"adds\": $DOC_LOCS, \"deletes\": []}" > /dev/null
    echo "✅ 임베딩 완료! 이제 클로드에서 스킬을 사용할 수 있습니다."
else
    echo "⚠️ 처리할 새로운 문서가 없습니다."
fi
