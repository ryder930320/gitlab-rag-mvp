# GitLab RAG 快速使用指南（一頁版）

---

## 🚀 啟動服務

**PowerShell（雙擊即可）：**
```powershell
.\start_rag.ps1
```

**Git Bash / WSL：**
```bash
./start_rag.sh
```

服務啟動後會顯示：
```
健康檢查: http://localhost:8001/health
查詢端點: http://localhost:8001/suggest?question=...
```

---

## 🔍 三種查詢方式

### 1. 最簡單：`ask.py`（推薦日常使用）
```bash
python ask.py "您的中文問題" [--top N] [--raw]
```
**範例：**
```bash
python ask.py "GPIO 控制怎麼用？"
python ask.py "how to set I2C speed" --top 3
python ask.py "建立 whl 安裝包" --raw   # 輸出完整 JSON
```

### 2. 瀏覽器 / curl（適合分享、測試）
```bash
# 中文查詢（GET，需 URL encode）
curl "http://localhost:8001/suggest?question=GPIO%20%E6%8E%A7%E5%88%B6&top_k=5"

# POST（支援完整 Unicode，推薦）
curl -X POST "http://localhost:8001/suggest" \
  -H "Content-Type: application/json" \
  -d '{"question": "GPIO 控制怎麼用？", "top_k": 5}'

# 純檢索（不生成建議，極快）
curl "http://localhost:8001/query?question=I2C%20speed&top_k=10"
```

### 3. Python 直接呼叫（整合到腳本、批次處理）
```python
import sys
sys.path.insert(0, r'C:\Users\YuchiPan\hermes-workspace\gitlab-rag-mvp\src')
from gitlab_rag.core.rag_interface import get_coding_suggestion

result = get_coding_suggestion("您的問題", top_k=5)
print(result["confidence"])
print(result["suggestion"])
for s in result["sources"]:
    print(f"  [{s['source_id']}] {s['file_path']} chunk#{s['chunk_index']}")
```

---

## 📋 回傳格式

### `/suggest`（生成建議）
```json
{
  "suggestion": "建議內容...",
  "confidence": "high|medium|low",
  "confidence_reason": "Top-1/Top-2 差距...",
  "sources": [
    {"source_id": 1, "file_path": "aaeonFramework/AonGpio.c", "chunk_index": 2, "preview": "...", "rrf_score": 0.032}
  ]
}
```

### `/query`（純檢索）
```json
[
  {"content": "...", "file_path": "...", "rrf_score": 0.032, "vec_rank": 1, "bm25_rank": 5, "symbol_hits": 2}
]
```

---

## ⚠️ 已知限制

| 問題 | 說明 |
|------|------|
| **NIM 503 偶發** | 上游不穩，自動重試 3 次（10s/20s/40s），查詢可能慢 30-70 秒 |
| **索引非 aaeonFramework** | 目前為 `build_pyd` 專案，查 aaeonFramework 真實歷史問題命中率低；需重建索引（參考 ISSUES_LOG.md CP-30） |
| **PowerShell GET 中文** | 必須用 POST + JSON body，GET 參數帶中文會編碼錯誤 |

---

## 🛑 停止服務

```powershell
# 找 PID
netstat -ano | findstr :8001
# 終止
taskkill /F /PID <PID>
```

---

## 📁 關鍵檔案

| 檔案 | 用途 |
|------|------|
| `start_rag.ps1` / `start_rag.sh` | 一鍵啟動 |
| `ask.py` | 簡易查詢工具 |
| `USAGE.md` | 完整使用說明 |
| `ISSUES_LOG.md` | 所有問題記錄（含 CP-33 根因修復） |