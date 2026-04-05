#!/bin/bash
# check_and_ingest.sh — Incremental ingest: only upload new/changed files.
# Keeps a manifest of previously ingested file hashes to avoid re-upload.

set -euo pipefail

TARGET_RAG_FOLDER="$HOME/my_rag_docs"
FIXED_API_KEY="my-secret-rag-key-2026"
WORKSPACE_SLUG="my_rag"
MANIFEST="$TARGET_RAG_FOLDER/.rag_manifest"

# Ensure server is reachable
if ! curl -s -o /dev/null -w '' http://localhost:3001/api/v1/auth -H "Authorization: Bearer $FIXED_API_KEY" 2>/dev/null; then
    echo '{"status":"server_down","message":"AnythingLLM server is not running. Run setup_rag.sh or start the server first."}'
    exit 1
fi

# Ensure collector is reachable
if ! curl -s -o /dev/null http://localhost:8888 2>/dev/null; then
    echo '{"status":"collector_down","message":"Collector server (port 8888) is not running."}'
    exit 1
fi

touch "$MANIFEST"
DOC_LOCS="["
CHANGED=0

shopt -s nullglob
for file in "$TARGET_RAG_FOLDER"/*; do
    [ -f "$file" ] || continue
    [[ "$(basename "$file")" == .* ]] && continue  # skip hidden/manifest

    HASH=$(sha256sum "$file" | cut -d' ' -f1)
    BASENAME=$(basename "$file")
    PREV_HASH=$(grep "^$BASENAME " "$MANIFEST" 2>/dev/null | awk '{print $2}' || true)

    if [ "$HASH" = "$PREV_HASH" ]; then
        continue  # unchanged
    fi

    echo ">>> 새로/변경 파일 인제스트: $BASENAME"
    RES=$(curl -s -X POST http://localhost:3001/api/v1/document/upload \
         -H "Authorization: Bearer $FIXED_API_KEY" \
         -F "file=@$file")

    LOC=$(echo "$RES" | jq -r '.documents[0].location // empty')

    if [ -n "$LOC" ]; then
        DOC_LOCS="$DOC_LOCS\"$LOC\","
        # Update manifest
        grep -v "^$BASENAME " "$MANIFEST" > "$MANIFEST.tmp" 2>/dev/null || true
        echo "$BASENAME $HASH" >> "$MANIFEST.tmp"
        mv "$MANIFEST.tmp" "$MANIFEST"
        CHANGED=$((CHANGED + 1))
    fi
done

DOC_LOCS="${DOC_LOCS%,}]"
if [ "$DOC_LOCS" == "]" ]; then DOC_LOCS="[]"; fi

if [ "$DOC_LOCS" != "[]" ]; then
    curl -s -X POST "http://localhost:3001/api/v1/workspace/$WORKSPACE_SLUG/update-embeddings" \
         -H "Authorization: Bearer $FIXED_API_KEY" \
         -H "Content-Type: application/json" \
         -d "{\"adds\": $DOC_LOCS, \"deletes\": []}" > /dev/null
fi

echo "{\"status\":\"ok\",\"changed\":$CHANGED,\"message\":\"$CHANGED files ingested\"}"
