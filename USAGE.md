# GitLab RAG 使用方式速查表

---

## 🚀 一鍵啟動

| 環境 | 執行方式 |
|------|----------|
| **PowerShell** (Windows 原生) | 雙擊 `start_rag.ps1` 或右鍵「以 PowerShell 執行」 |
| **Git Bash / WSL** | `./start_rag.sh` |
| **手動啟動** | 見下方「手動啟動步驟」 |

啟動成功後會顯示：
```
健康檢查: http://localhost:8001/health
查詢端點: http://localhost:8001/suggest?question=您的問題&top_k=5
```

---

## 🔍 查詢方式（三種）

### 1. 瀏覽器 / 圖形化工具（最直觀）

**健康檢查**
```
http://localhost:8001/health
```

**中文查詢（GET，URL 編碼）**
```
http://localhost:8001/suggest?question=GPIO%20%E6%8E%A7%E5%88%B6%E6%80%8E%E9%BA%BC%E7%94%A8%EF%BC%9F&top_k=5
```

**英文查詢**
```
http://localhost:8001/suggest?question=how%20to%20set%20device&top_k=5
```

**純檢索（不生成建議）**
```
http://localhost:8001/query?question=I2C%20speed&top_k=10
```

> 💡 瀏覽器直接貼上網址即可，回傳 JSON 可直接閱讀或存成檔案。

---

### 2. 命令列（curl / PowerShell Invoke-RestMethod）

#### PowerShell (Windows 原生)
```powershell
# 中文查詢 - 必須用 URL 編碼
$q = "GPIO 控制怎麼用？"
$encoded = [System.Web.HttpUtility]::UrlEncode($q)
Invoke-RestMethod "http://localhost:8001/suggest?question=$encoded&top_k=5" | ConvertTo-Json -Depth 5

# 英文查詢
Invoke-RestMethod "http://localhost:8001/suggest?question=how to set device&top_k=5" | ConvertTo-Json -Depth 5

# POST 方式（避開 URL 長度限制、支援特殊字元）
$body = @{ question = "GPIO 控制怎麼用？"; top_k = 5 } | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:8001/suggest" -Method Post -Body $body -ContentType "application/json" | ConvertTo-Json -Depth 5
```

#### Git Bash / Linux / curl
```bash
# 中文查詢 (GET)
curl "http://localhost:8001/suggest?question=GPIO%20%E6%8E%A7%E5%88%B6%E6%80%8E%E9%BA%BC%E7%94%A8%EF%BC%9F&top_k=5"

# POST 方式（推薦，支援完整 Unicode，不需手動編碼）
curl -X POST "http://localhost:8001/suggest" \
  -H "Content-Type: application/json" \
  -d '{"question": "GPIO 控制怎麼用？", "top_k": 5}'

# 純檢索
curl "http://localhost:8001/query?question=I2C%20speed&top_k=10"
```

---

### 3. Python 直接呼叫（無需 HTTP，適合整合到腳本）

```python
import sys
sys.path.insert(0, r'C:\Users\YuchiPan\hermes-workspace\gitlab-rag-mvp\src')

from gitlab_rag.core.rag_interface import query_gitlab_context, get_coding_suggestion

# 1. 純檢索（回傳 chunks 列表）
chunks = query_gitlab_context("GPIO 控制怎麼用？", top_k=5, use_hybrid=True)
for c in chunks:
    print(f"{c['rrf_score']:.4f} | {c['file_path']} | chunk#{c['chunk_index']}")
    print(f"  {c['content'][:100]}...")

# 2. 完整生成（含信心等級、來源、建議文字）
result = get_coding_suggestion("如何設定 I2C 速率？", top_k=5)

print(f"\n信心等級: {result['confidence']}")
print(f"理由: {result['confidence_reason']}")
print(f"\n建議內容:\n{result['suggestion']}")
print(f"\n引用來源:")
for s in result['sources']:
    print(f"  [{s['source_id']}] {s['file_path']} chunk#{s['chunk_index']} (rrf={s['rrf_score']:.4f})")
```

---

## 📋 回傳格式說明

### `/suggest` 回傳
```json
{
  "suggestion": "生成的建議文字...",
  "confidence": "high | medium | low",
  "confidence_reason": "Top-1/Top-2 差距較大...",
  "sources": [
    {
      "source_id": 1,
      "file_path": "aaeonFramework/AonGpio.c",
      "chunk_index": 2,
      "preview": "內容前 200 字...",
      "rrf_score": 0.0320,
      "symbol_hits": 3
    }
  ]
}
```

### `/query` 回傳（純檢索）
```json
[
  {
    "content": "chunk 內容...",
    "file_path": "aaeonFramework/AonGpio.c",
    "source_type": "code",
    "chunk_index": 2,
    "rrf_score": 0.0320,
    "vec_rank": 1,
    "bm25_rank": 5,
    "symbol_hits": 3
  }
]
```

---

## ⚠️ 常見問題

| 問題 | 解決方式 |
|------|----------|
| **PowerShell 中文亂碼** | 用 POST + JSON body，不要用 GET 參數帶中文 |
| **端口被佔用** | 執行 `start_rag.ps1` 會自動詢問是否終止舊進程；或手動 `netstat -ano \| findstr :8001` 找 PID → `taskkill /F /PID <PID>` |
| **虛擬環境未啟動** | 手動執行 `.venv\Scripts\Activate.ps1` 後再跑指令 |
| **NIM API 503/429** | 系統內建限流 (35 RPM) + 重試，偶發 503 等待幾秒重試即可 |
| **索引不是 aaeonFramework** | 目前索引為 `build_pyd` 專案，需重建索引才能對 aaeonFramework 真實問題有高命中率（參考 ISSUES_LOG.md CP-30） |

---

## 🛑 停止服務

```powershell
# PowerShell
netstat -ano | findstr :8001
taskkill /F /PID <PID>
```

```bash
# Git Bash
netstat -ano | grep 8001
taskkill //F //PID <PID>
# 或
kill -9 <PID>
```

---

## 📁 專案結構速覽

```
gitlab-rag-mvp/
├── start_rag.ps1          # 一鍵啟動 (PowerShell)
├── start_rag.sh           # 一鍵啟動 (Bash)
├── src/gitlab_rag/
│   ├── api/app.py         # FastAPI 端點 (/health, /suggest, /query)
│   ├── core/
│   │   ├── hybrid_search.py      # 混合檢索 (RRF)
│   │   ├── generate_coding_suggestion.py  # 生成建議
│   │   ├── rate_limiter.py       # 全局限流 35 RPM
│   │   └── nim_logger.py         # SQLite + JSONL 記錄
│   └── data_ingestion/    # 索引建立腳本
├── data/                  # 索引、資料庫、快取
└── ISSUES_LOG.md          # 所有問題記錄
```

---

## 🎯 一句話摘要

> **雙擊 `start_rag.ps1` → 瀏覽器開 `http://localhost:8001/suggest?question=您的問題&top_k=5` → 即可查詢**  
> 若要整合進腳本：`from gitlab_rag.core.rag_interface import get_coding_suggestion`