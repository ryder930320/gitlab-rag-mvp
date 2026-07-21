# GitLab RAG — Hybrid Search (CP-25 Complete)

> **Branch**: `v3-cp25` | **Tag**: `v3.0-cp25`
> **⚠️ 凍結版本記錄 — 不再更新** | 基準點：CP-25 完成，評估框架與 18 題基準已驗收

---

結合 **向量檢索 + BM25 關鍵字檢索 + 程式碼符號加分** 的混合檢索系統，解決純向量檢索在「查詢詞與程式碼符號不匹配」時表現差的問題。

---

## 🎯 核心特色

| 功能 | 說明 |
|------|------|
| **向量檢索** | NVIDIA `nv-embedqa-e5-v5` (1024-dim)，語意相似度 |
| **BM25 關鍵字檢索** | 字符級 3-gram，解決中文查詢匹配英文程式碼 |
| **符號加分** | 自動抽取函式/類別/檔名，查詢匹配時 +0.2 bonus |
| **RRF 融合** | Reciprocal Rank Fusion (k=60)，解決分數尺度問題 |
| **查詢擴展** | 純中文查詢自動擴展英文技術術語，僅餵給 BM25/符號路徑 |
| **Reranker** | Nemotron-3-Ultra 生成式重排序，串接於 RRF 後 |
| **三級信心評估** | High / Medium / Low (含不確定性區間) |
| **生成建議** | Nemotron-3-Ultra 生成程式碼建議，附來源引用 |
| **雙端點** | `/query` (純檢索) + `/suggest` (含生成建議) |

---

## 📦 架構圖

```
User Query
    │
    ├─► Vector Search (Chroma) ──► vec_rank
    │
    ├─► BM25 Search (char 3-gram) ──► bm25_rank
    │
    ├─► Symbol Match (def/class/filename/call/import/const) ──► symbol_rank
    │
    └─► Query Expansion (純中文查詢) ──► 僅餵給 BM25/符號路徑
           │
           ▼
    RRF Fusion (k=60) ──► Top-K
           │
           ▼
    Reranker (Nemotron-3-Ultra) ──► rerank_score
           │
           ▼
    Confidence Evaluator (rerank_median + MAD + RRF gap) ──► High/Medium/Low
           │
           ▼
    Generate Suggestion (Nemotron-3-Ultra) ──► /suggest 端點
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
NIM_GENERATE_MODEL=nvidia/nemotron-3-ultra-550b-a55b
```

### 3. 建立索引（首次執行）
```bash
# CP-2~5: 抓資料 → 切分 → Embedding → 寫入 Chroma
python gitlab_client.py
python fetch_and_save.py
python chunking.py
python embed_and_store.py

# CP-8: BM25 索引 + 符號抽取
python keyword_index.py
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
from rag_interface import query_gitlab_context, get_coding_suggestion

# 混合檢索（預設）
results = query_gitlab_context("專案怎麼處理 GPIO 控制？", top_k=5)

# 純向量檢索（對照用）
results = query_gitlab_context("專案怎麼處理 GPIO 控制？", top_k=5, use_hybrid=False)

# 含生成建議
suggestion = get_coding_suggestion("專案怎麼處理 GPIO 控制？", top_k=5)
# 回傳: suggestion, confidence, confidence_reason, sources
```

### HTTP API
```bash
# 純檢索
curl "http://localhost:8000/query?question=專案怎麼處理 GPIO 控制？&top_k=5&use_hybrid=true"

# 含生成建議
curl "http://localhost:8000/suggest?question=專案怎麼處理 GPIO 控制？&top_k=5"

# POST (含中文請用檔案傳遞)
printf '%s' '{"question": "專案怎麼處理 GPIO 控制？", "top_k": 5}' > payload.json
curl -s -X POST "http://localhost:8000/suggest" -H "Content-Type: application/json" --data-binary @payload.json

# 健康檢查
curl http://localhost:8000/health
```

### 回傳格式
```json
{
  "question": "專案怎麼處理 GPIO 控制？",
  "suggestion": "GPIO 控制透過 GPIO 類別...",
  "confidence": "high",
  "confidence_reason": "rerank 中位數 0.95 > 0.85 且穩定...",
  "sources": [
    {
      "file_path": "build_pyd/device_controll.py",
      "chunk_index": 1,
      "preview": "class GPIO: ...",
      "rerank_score": 0.95
    }
  ]
}
```

---

## 📂 專案結構

```
gitlab-rag-mvp/
├── .env                    # 密鑰（不提交）
├── .env.example            # 範本
├── .gitignore
├── requirements.txt
├── CHANGELOG.md            # 變更日誌
├── ISSUES_LOG.md           # 問題追蹤總表
├── AGENTS.md               # 專案執行規範
│
├── gitlab_client.py        # CP-2: GitLab API 擷取
├── fetch_and_save.py       # CP-3: 原始資料落地
├── chunking.py             # CP-4: 文字切分 (1000 chars / 150 overlap)
├── embed_and_store.py      # CP-5: Embedding + Chroma (32 RPM 限流)
├── keyword_index.py        # CP-8: BM25 索引 + 符號抽取
├── hybrid_search.py        # CP-9/13: 混合檢索融合邏輯 (RRF)
├── query.py                # CP-6: 測試腳本
│
├── src/gitlab_rag/
│   ├── __init__.py
│   ├── app.py              # CP-19: FastAPI HTTP 端點
│   ├── rag_interface.py    # CP-11: 核心介面 (use_hybrid 開關)
│   ├── query_expander.py   # CP-23: 純中文查詢擴展
│   ├── reranker.py         # CP-24: Nemotron-3-Ultra 重排序
│   ├── confidence_evaluator.py  # CP-17/25: 三級信心評估 (不確定性區間)
│   ├── generate_coding_suggestion.py  # CP-18: 生成建議
│   ├── low_confidence_threshold.py  # CP-25: Low 信心門檻 (連續分數+不確定性)
│   ├── evaluate_faithfulness.py  # CP-25: Faithfulness 評估 (多次取中位數)
│   ├── nim_logger.py       # CP-26: NIM API 呼叫持久化 (SQLite+JSONL)
│   ├── hybrid_search.py    # CP-9/13: RRF 融合
│   ├── keyword_index.py    # CP-8: BM25 索引
│   ├── chunking.py         # CP-4: 切分
│   ├── embed_and_store.py  # CP-5: Embedding
│   ├── gitlab_client.py    # CP-2: GitLab 擷取
│   └── ...                 # 其他模組
│
├── data/                   # 原始資料與 chunks
└── chroma_db/              # 向量資料庫
```

---

## ⚙️ 關鍵參數

| 參數 | 值 | 說明 |
|------|-----|------|
| `k` (RRF) | 60 | RRF 融合參數 |
| `chunk_size` | 1000 | 字元切分長度 |
| `chunk_overlap` | 150 | 重疊長度 |
| `ngram_n` | 3 | BM25 字符級 n-gram |
| `symbol_bonus` | 0.2 | 符號匹配加分 |
| `rate_limit` | 32 RPM | NIM Embedding API 限流 |
| `rerank_model` | Nemotron-3-Ultra | 生成式重排序 |
| `generate_model` | Nemotron-3-Ultra | 生成建議 |
| `judge_model` | Nemotron-3-Ultra | Faithfulness 評審 |

---

## ⚠️ 已知限制（誠實記錄）

1. **POST 端點中文 body 解析失敗** — Windows/MSYS 環境下 POST /query、POST /suggest 無法正確解析包含中文的 JSON body (HTTP 400)；GET 端點完全正常。此為 MSYS/curl/終端機編碼層面限制，**非應用層缺陷**，研判為環境層面限制。

2. **NIM 免費額度限制** — Nemotron-3-Ultra 偶發 timeout (60s) 或 503/429，生產環境建議自備 API Key 或部署本地模型。

3. **Low 信心路徑未經真實資料觸發** — 語料庫以 device_controll.py 為主，向量/BM25 排名普遍不差，導致 vec_rank>5 且 bm25_rank>8 且 symbol_hits=0 條件難同時成立。單元測試構造資料已驗證邏輯正常。

4. **純中文查詢效能受限** — 若查詢不含英文術語（如 whl、gpio、infer），符號匹配失效，完全依賴向量模型語意匹配。

5. **whl 無法被符號匹配** — 僅在 note.txt 內容出現 (bdist_wheel)，不在任何函式/類別名稱中，無法被 symbol_token 匹配。

5. **RRF 融合權重固定** — 目前三路檢索 (向量/BM25/符號) 權重均等，未針對特定查詢類型動態調整。

7. **Faithfulness 評估極端非確定性** — 同一答案三次評審可達 5-6 倍差距 (MAD 掩蓋極端離散)，建議後續 n_runs=5 或多模型評審。

---

## 📋 回歸測試結果 (CP-30-C 130 題真實歷史題)

### CP-30-C 真實歷史驗證 (130 題, aaeonFramework 專案)

| 分類 | 題數 | Top-3 命中率 | Confidence 分布 |
|------|------|-------------|-----------------|
| **明確技術修復** | 9 | **100.0%** (9/9) | high 3, medium 4, low 2 |
| **純功能支援** | 121 | **93.4%** (113/121) | high 32, medium 78, low 11 |

**整體 Top-3 命中率: 93.8% (122/130)**，Chroma 相關 error: 0/130

> 注：原 CP-30-C 回報 89.2%（含 8 題 error），經 Chroma 併發修復、check_file_hit 全量核對後更新為 93.8%、0 errors。

---

## 🏷️ 版本歷程

---

## 🏷️ 版本歷程

| Tag | Commit | 說明 |
|-----|--------|------|
| `v0-mvp-cp0-7` | ae1172f | MVP：純向量檢索 |
| `v1-hybrid-cp8-11` | 55b78a0 | Hybrid Search：BM25 + 向量融合 |
| `v2-techdebt-cp12-15` | 8460547 | 技術債清理：RRF + 符號自動映射 + 符號擴充 |
| `v3-generation-cp16-20` | 86a9967 | 生成整合：Prompt/信心/生成 + HTTP 端點 + 回歸測試 |
| **`v3.0-cp25`** | **07ec1de** | **評估框架：Faithfulness 多次取中位數 + Low 門檻校準 + 完整 18 題基準** |

---

## ⚠️ 版本記錄鎖定聲明

> **本分支 (v3-cp25) 為 CP-25 完成之凍結版本記錄，不再接受功能性修改。**
> - 後續開發請基於新分支
> - 僅接受文檔錯字修正，不接受架構/代碼/流程變更
> - 歷史基準點：CP-25 完成，Faithfulness 多次取中位數評估框架 + Low 門檻校準 + 完整 18 題基準 + CP-26 log 缺口補齊