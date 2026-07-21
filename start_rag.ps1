<#>
.SYNOPSIS
    GitLab RAG 一鍵啟動腳本 (PowerShell 版)
.DESCRIPTION
    自動啟動虛擬環境、檢查端口、啟動 API 服務
#>

$ErrorActionPreference = "Stop"

Write-Host "=== GitLab RAG 啟動器 ===" -ForegroundColor Cyan

# 專案路徑
$projectRoot = "C:\Users\YuchiPan\hermes-workspace\gitlab-rag-mvp"
$venvPath = "$projectRoot\.venv\Scripts\Activate.ps1"
$port = 8001

# 切換目錄
Set-Location $projectRoot
Write-Host "工作目錄: $projectRoot" -ForegroundColor Gray

# 檢查虛擬環境
if (-not (Test-Path $venvPath)) {
    Write-Host "❌ 找不到虛擬環境: $venvPath" -ForegroundColor Red
    Write-Host "請先執行: python -m venv .venv && .venv\Scripts\pip install -r requirements.txt" -ForegroundColor Yellow
    Read-Host "按 Enter 結束"
    exit 1
}

# 啟動虛擬環境
Write-Host "啟動虛擬環境..." -ForegroundColor Gray
. $venvPath

# 檢查端口是否被佔用
$portInUse = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
if ($portInUse) {
    Write-Host "⚠️ 端口 $port 已被佔用 (PID: $($portInUse.OwningProcess))" -ForegroundColor Yellow
    $choice = Read-Host "是否嘗試終止該進程並繼續? (y/n)"
    if ($choice -eq 'y') {
        Stop-Process -Id $portInUse.OwningProcess -Force -ErrorAction SilentlyContinue
        Start-Sleep 1
        Write-Host "已終止舊進程" -ForegroundColor Green
    } else {
        Write-Host "啟動取消" -ForegroundColor Red
        Read-Host "按 Enter 結束"
        exit 1
    }
}

# 檢查 .env
if (-not (Test-Path "$projectRoot\.env")) {
    Write-Host "❌ 找不到 .env 檔案，請先設定 NIM_API_KEY" -ForegroundColor Red
    Read-Host "按 Enter 結束"
    exit 1
}

Write-Host "啟動 API 服務 (port $port)..." -ForegroundColor Cyan
Write-Host "健康檢查: http://localhost:$port/health" -ForegroundColor Gray
Write-Host "查詢端點: http://localhost:$port/suggest?question=您的問題&top_k=5" -ForegroundColor Gray
Write-Host "按 Ctrl+C 停止服務" -ForegroundColor Gray
Write-Host ""

# 啟動 uvicorn (前景模式，方便看 log)
try {
    uvicorn src.gitlab_rag.api.app:app --port $port --host 0.0.0.0
} catch {
    Write-Host "❌ 啟動失敗: $($_.Exception.Message)" -ForegroundColor Red
    Read-Host "按 Enter 結束"
}