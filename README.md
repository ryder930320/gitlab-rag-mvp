# GitLab RAG — Hybrid Search (CP-11)

> **Branch**: `master` | **Tag**: `v1.0-hybrid-cp11`

結合 **向量檢索 + BM25 關鍵字檢索 + 程式碼符號加分** 的混合檢索系統，解決純向量檢索在「查詢詞與程式碼符號不匹配」時表現差的問題。

---

## 🎯 核心特色

| 功能 | 說明 |
|------|------|
| **向量檢索** | NVIDIA `nv-embedqa-e5-v5` (1024-dim)，語意相似度 |
| **BM25 關鍵字檢索** | 字符級 3-gram，解決中文查詢匹配英文程式碼 |
| **符號加分** | 自動抽取函式/類別/檔名，查詢匹配時 +0.2 bonus |
| **加權融合** | `final = 0.5 × norm_vec + 0.5 × norm_bm25 + symbol_bonus` |
| **雙模式開關** | `use_hybrid=True/False` 支援 A/B 對照 |

---

## 📦 架構圖

```
User Query
    │
    ├─► Vector Search (Chroma) ──► score_vector
    │
    ├─► BM25 Search (char 3-gram) ──► score_bm25
    │
    └─► Symbol Match (def/class/filename) ──► symbol_bonus
           │
           ▼
    Weighted Fusion (α=0.5) ──► Top-K Results
```

---

## 🚀 快速開始

### 1. 環境設定
```bash
git clone https://github.com/ryder930320/gitlab-rag-mvp.git
cd gitlab-rag-mvp
python -m venv .venv
.venv/Scripts/activate
pip install -r requirements.txt
```

### 2. 設定 `.env`
```ini
GITLAB_URL=https://your-gitlab.com
GITLAB_TOKEN=glpat-xxxxx
GITLAB_PROJECT=123
NIM_API_KEY=nvapi-xxxxx
NIM_EMBED_MODEL=nvidia/nv-embedqa-e5-v5
```

### 3. 建立索引（首次執行）
```bash
# CP-2~5: 抓資料 → 切分 → Embedding → 寫入 Chroma
python gitlab_client.py
python fetch_and_save.py
python chunking.py
python embed_and_store.py
```

### 4. 啟動 API 服務
```bash
python app.py
# → http://localhost:8000
```

---

## 🔌 API 使用

### 查詢介面
```python
from rag_interface import query_gitlab_context

# 混合檢索（預設）
results = query_gitlab_context("專案怎麼處理 GPIO 控制？", top_k=5)

# 純向量檢索（對照用）
results = query_gitlab_context("專案怎麼處理 GPIO 控制？", top_k=5, use_hybrid=False)
```

### HTTP API
```bash
# 混合檢索
curl "http://localhost:8000/query?question=專案怎麼處理 GPIO 控制？&top_k=5&use_hybrid=true"

# 純向量檢索
curl "http://localhost:8000/query?question=專案怎麼處理 GPIO 控制？&top_k=5&use_hybrid=false"

# 健康檢查
curl http://localhost:8000/health
```

### 回傳格式
```json
{
  "question": "專案怎麼處理 GPIO 控制？",
  "results": [
    {
      "content": "def set_dio_status(self, num, io, lv): ...",
      "file_path": "build_pyd/device_controll.py",
      "source_type": "code",
      "language": "py",
      "chunk_index": 5,
      "created_at": "",
      "score": 0.9525
    }
  ],
  "count": 5
}
```

---

## 📂 專案結構

```
gitlab-rag-mvp/
├── .env                    # 密鑰（不提交）
├── .env.example            # 範本
├── .gitignore
├── requirements.txt        # python-gitlab, chromadb, httpx, python-dotenv, rank-bm25
├── ISSUES_LOG.md           # 問題追蹤總表
│
├── gitlab_client.py        # CP-2: GitLab API 擷取
├── fetch_and_save.py       # CP-3: 原始資料落地
├── chunking.py             # CP-4: 文字切分 (1000 chars / 150 overlap)
├── embed_and_store.py      # CP-5: Embedding + Chroma (32 RPM 限流)
├── keyword_index.py        # CP-8: BM25 索引 + 符號抽取
├── hybrid_search.py        # CP-9/10: 混合檢索融合邏輯
├── query.py                # CP-6: 測試腳本
│
├── rag_interface.py        # CP-11: 核心介面 (use_hybrid 開關)
├── app.py                  # CP-11: FastAPI HTTP 端點
│
├── data/                   # 原始資料與 chunks
└── chroma_db/              # 向量資料庫
```

---

## ⚙️ 關鍵參數

| 參數 | 值 | 說明 |
|------|-----|------|
| `alpha` | 0.5 | 向量/BM25 等權重 |
| `chunk_size` | 1000 | 字元切分長度 |
| `chunk_overlap` | 150 | 重疊長度 |
| `ngram_n` | 3 | BM25 字符級 n-gram |
| `symbol_bonus` | 0.2 | 符號匹配加分 |
| `rate_limit` | 32 RPM | NIM API 速率限制 |

---

## ⚠️ 已知限制

1. **查詢擴展硬編碼** — `QUERY_EXPANSION` 字典僅覆蓋測試題詞彙，換 repo 需人工更新
2. **Min-Max 正規化 batch-dependent** — 資料量增大時分數尺度會漂移，需改用分位數或 log-scaling
3. **符號抽取覆蓋率不足** — 僅抓 `def`/`class`，遺漏 import、方法呼叫、常數

詳細紀錄見 [ISSUES_LOG.md](ISSUES_LOG.md)。

---

## 🏷️ 版本

| 分支 | 版本 | 描述 |
|------|------|------|
| `master` | `v1.0-hybrid-cp11` | Hybrid Search (CP-11) |
| `mvp-baseline` | `v1.0-mvp` | 純向量檢索 (CP-7) |

```bash
git checkout mvp-baseline   # 切換到 MVP 純向量版
git checkout master         # 切換回 Hybrid 版
```

---

## 📜 授權

MIT License