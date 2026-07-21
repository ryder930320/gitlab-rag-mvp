#!/usr/bin/env bash
# GitLab RAG 一鍵啟動腳本 (Bash 版，適用 Git Bash / WSL / Linux)

set -euo pipefail

PROJECT_ROOT="/c/Users/YuchiPan/hermes-workspace/gitlab-rag-mvp"
VENV_ACTIVATE="$PROJECT_ROOT/.venv/Scripts/activate"
PORT=8001

echo "=== GitLab RAG 啟動器 ==="
echo "工作目錄: $PROJECT_ROOT"
cd "$PROJECT_ROOT"

# 檢查虛擬環境
if [[ ! -f "$VENV_ACTIVATE" ]]; then
    echo "❌ 找不到虛擬環境: $VENV_ACTIVATE"
    echo "請先執行: python -m venv .venv && source .venv/Scripts/activate && pip install -r requirements.txt"
    read -p "按 Enter 結束..."
    exit 1
fi

# 啟動虛擬環境
echo "啟動虛擬環境..."
source "$VENV_ACTIVATE"

# 檢查端口佔用
if netstat -ano 2>/dev/null | grep -q ":$PORT "; then
    PID=$(netstat -ano 2>/dev/null | grep ":$PORT " | awk '{print $NF}' | head -1)
    echo "⚠️ 端口 $PORT 已被佔用 (PID: $PID)"
    read -p "是否嘗試終止該進程並繼續? (y/n) " choice
    if [[ "$choice" == "y" ]]; then
        taskkill //F //PID "$PID" 2>/dev/null || kill -9 "$PID" 2>/dev/null
        sleep 1
        echo "已終止舊進程"
    else
        echo "啟動取消"
        read -p "按 Enter 結束..."
        exit 1
    fi
fi

# 檢查 .env
if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
    echo "❌ 找不到 .env 檔案，請先設定 NIM_API_KEY"
    read -p "按 Enter 結束..."
    exit 1
fi

echo "啟動 API 服務 (port $PORT)..."
echo "健康檢查: http://localhost:$PORT/health"
echo "查詢端點: http://localhost:$PORT/suggest?question=您的問題&top_k=5"
echo "按 Ctrl+C 停止服務"
echo ""

# 啟動 uvicorn (前景模式)
uvicorn src.gitlab_rag.api.app:app --port "$PORT" --host 0.0.0.0