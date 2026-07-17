#!/usr/bin/env bash
# GitLab RAG API 輸入中文查詢的正確方式 (Windows/MSYS 環境)
# 用法: rag_post "中文查詢內容" [top_k]
# 範例: rag_post "GPIO 控制怎麼用？" 5

set -euo pipefail

API_URL="http://localhost:8000/suggest"
PAYLOAD_FILE="payload.json"

question="${1:-}"
top_k="${2:-5}"

if [[ -z "$question" ]]; then
    echo "用法: $0 \"查詢內容\" [top_k]"
    echo "範例: $0 \"GPIO 控制怎麼用？\" 5"
    exit 1
fi

# 使用 printf 寫入 UTF-8 JSON 檔案 (避開命令列編碼問題)
printf '%s' "{\"question\": \"$question\", \"top_k\": $top_k}" > "$PAYLOAD_FILE"

# 發送請求 (使用 --data-binary @檔案)
curl -s -X POST "$API_URL" \
    -H "Content-Type: application/json" \
    --data-binary @"$PAYLOAD_FILE" | python -m json.tool

# 清理
rm -f "$PAYLOAD_FILE"