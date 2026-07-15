# GitLab RAG MVP — 純向量檢索版本 (CP-1~7)

> **分支**: `mvp-baseline` ｜ **標籤**: `v1.0-mvp` ｜ **對應主分支**: `master` (Hybrid CP-11)

---

## 簡介

GitLab 專案程式碼 RAG 系統最小可行產品：**純向量檢索**，無 BM25、無混合融合、無查詢擴展。

- 輸入：自然語言問題
- 輸出：Top-K 相關程式碼 chunks（含檔案路徑、類型、相似度分數）
- 介面：本地 Python 函式 + FastAPI HTTP 端點

---

## 快速開始

### 1. 環境準備
```bash
git clone <repo-url>
cd gitlab-rag-mvp
git checkout mvp-baseline

# 建立虛擬環境
python -m venv .venv
.venv/Scripts/activate   # Windows
# source .venv/bin/activate  # Linux/Mac

pip install -r requirements.txt
```

### 2. 設定 `.env`
複製 `.env.example` 為 `.env` 並填入：
```env
GITLAB_URL=https://your-gitlab.com
GITLAB_TOKEN=glpat-xxxxx
GITLAB_PROJECT=123
NIM_API_KEY=nvapi-xxxxx
NIM_EMBED_MODEL=nvidia/nv-embedqa-e5-v5
```

### 3. 建立索引（只需跑一次）
```bash
python fetch_and_save.py      # 抓 GitLab 程式碼 + commit
python chunking.py            # 切分 chunks
python embed_and_store.py     # 產生 embedding 存入 Chroma
```

### 4. 查詢測試
```bash
# 本地函式
python -c "
from rag_interface import query_gitlab_context, format_results
res = query_gitlab_context('這個專案怎麼處理 GPIO 控制？', top_k=3)
print(format_results(res))
"

# HTTP API
python app.py
# GET  http://localhost:8000/query?question=xxx&top_k=5
# POST http://localhost:8000/query  {"question": "xxx", "top_k": 5}
```

---

## 專案結構

```
gitlab-rag-mvp/
├── .env.example
├── .gitignore
├── requirements.txt        # python-gitlab, chromadb, httpx, python-dotenv
│
├── gitlab_client.py        # CP-2: GitLab API 擷取
├── fetch_and_save.py       # CP-3: 原始資料落地
├── chunking.py             # CP-4: 文字切分 (1000 chars / 150 overlap)
├── embed_and_store.py      # CP-5: Embedding + Chroma (32 RPM 限流)
├── query.py                # CP-6: 測試腳本
│
├── rag_interface.py        # CP-7: 核心介面 (純向量)
├── app.py                  # CP-7: FastAPI HTTP 端點
│
├── data/                   # raw_files.json, raw_commits.json, chunks.json
└── chroma_db/              # 向量資料庫
```

---

## 介面規格

### 本地函式
```python
from rag_interface import query_gitlab_context

results = query_gitlab_context("問題", top_k=5)
# 回傳: list[dict]
# {
#   "content": str,
#   "file_path": str,
#   "source_type": "code|commit",
#   "language": str,
#   "chunk_index": int,
#   "created_at": str,
#   "score": float  # cosine similarity 0~1
# }
```

### HTTP API
```
GET  /query?question=xxx&top_k=5
POST /query  {"question": "xxx", "top_k": 5}
GET  /health
```

回傳：
```json
{
  "question": "xxx",
  "results": [...],
  "count": 5
}
```

---

## 關鍵參數

| 參數 | 值 |
|------|-----|
| Embedding 模型 | `nvidia/nv-embedqa-e5-v5` (1024-dim) |
| Chunk 大小 | 1000 chars |
| Chunk 重疊 | 150 chars |
| 速率限制 | 32 RPM (NIM API) |
| 向量庫 | Chroma (cosine) |

---

## 與 Hybrid 版本差異

| 功能 | MVP (mvp-baseline) | Hybrid (master) |
|------|-------------------|-----------------|
| 檢索方式 | 純向量 | 向量 + BM25 + 符號加分 |
| 查詢擴展 | 無 | 硬編碼字典 |
| 符號加分 | 無 | 有 (0.2 bonus) |
| `use_hybrid` 參數 | 無 | 有 |
| 依賴套件 | 無 `rank-bm25` | 需 `rank-bm25` |

---

## 版本標籤

```bash
git checkout mvp-baseline   # 本分支
git tag v1.0-mvp            # 標籤

git checkout master         # Hybrid 版本
git tag v1.0-hybrid-cp11    # 標籤
```

---

## 授權

MIT License