# GitLab RAG MVP - 變更日誌

所有功能新增、修復、優化的完整記錄，按時間倒序排列。

---

## [2025-07-21] - 階段延遲追蹤 + SSE 串流 + 前端即時顯示

### 新增
- **API `/suggest/timing`**：同步端點，回傳完整建議 + 各階段詳細延遲 (ms)
  - `hybrid_search_ms`：Hybrid Search (embedding + BM25 + RRF) 耗時
  - `confidence_eval_ms`：信心評估耗時
  - `prompt_build_ms`：Prompt 建構耗時
  - `llm_generate_ms`：LLM 生成耗時（佔總耗時 ~95%）
  - `total_ms`：總耗時
- **API `/suggest/stream`**：SSE (Server-Sent Events) 串流端點
  - 階段 1：`search` / `search_done` - Hybrid Search 完成
  - 階段 2：`confidence` / `confidence_done` - 信心評估完成
  - 階段 3：`prompt` / `prompt_done` - Prompt 建構完成
  - 階段 4：`generate` / `token` / `complete` - LLM 串流生成 (逐 token 回傳)
  - 最終 `complete` 階段回傳完整結果 + 完整 timing
- **前端 `rag_ui.html` SSE 整合**
  - 階段進度條 + 進度百分比
  - 即時 token 串流顯示 (含閃爍游標動畫)
  - Timing 面板：各階段耗時表格 + 總計
  - 新增「串流查詢」按鈕，可選擇一般查詢或串流查詢
- **後端 import 路徑修正**：`src.gitlab_rag.*` → `..core.*` 相對導入

### 修復
- 修正 `suggest_with_timing` 端點的相對導入路徑 (`src.gitlab_rag` → `..core`)
- 修正 SSE 生成器中 `rag_interface` 導入路徑
- 修正 SSE 生成器縮進錯誤

---

## [2025-07-21] - Pipeline Timing Script + 階段延遲分析

### 新增
- **`scripts/pipeline_timing.py`**：獨立可執行的 Pipeline 計時腳本
  - 8 個階段獨立計時：query_expand, embedding, hybrid_search, rerank, confidence_eval, prompt_build, llm_generate
  - 輸出美觀表格：階段、耗時(ms)、佔比、備註
  - CLI 介面：`python scripts/pipeline_timing.py "問題" [top_k]`
  - 分析結果：LLM 生成佔總耗時 ~95% (56.8s/59.7s)

### 分析結果
| 階段 | 耗時(ms) | 佔比 | 結論 |
|------|---------|------|------|
| LLM Generate | 56,776 | 95% | **主要瓶頸** |
| Hybrid Search | 1,972 | 3.3% | 正常 |
| Embedding | 989 | 1.7% | 正常 |
| 其他 | < 5ms | < 0.1% | 可忽略 |

---

## [2025-07-21] - CORS 修復 + SSE 支援

### 修復
- **CORS 設定**：`allow_origins=["*"]` + `allow_credentials=False` 解決 `file://` 開啟 HTML 時的 CORS 錯誤
- **Origin: null 支援**：Starlette TestClient 驗證通過
- **SSE 端點 CORS**：`/suggest/stream` 支援 `Origin: file://` (瀏覽器送 `Origin: null`)

### 驗證
```python
# 測試通過項目
✅ OPTIONS /suggest preflight: 200
✅ POST /suggest with Origin: 200
✅ GET /query with Origin: 200
✅ POST /query with Origin: 200
✅ GET /health: 200
```

---

## [2025-07-21] - 全局限流器 + NIM Logger Header 記錄

### 新增
- **`src/gitlab_rag/core/rate_limiter.py`**：全局單例限流器
  - 35 RPM 保守值 (NVIDIA 免費層 40 RPM 的 87.5%)
  - Embedding + Generate 共用同一配額池 (NVIDIA 免費層帳號級共用配額)
  - 滑動窗口實現，線程安全
  - 動態調整規則：連續 24h 無 429 → 嘗試調高 20% (上限 38 RPM)；出現 429 → 立即打八折
  - `adjustment_history` 記錄所有調整歷史

### 修復
- **`nim_logger.py` 新增 `response_headers` 參數**：自動過濾記錄 `rate`/`retry`/`limit`/`reset` 相關 header
- **最小等待保護**：`Retry-After` 為空/0/非數字時，最小等待 10s
- **503 重試邏輯統一**：與 429 共用指數退避

### 關鍵發現
> **NVIDIA 免費層實際配額**：40 RPM (帳號級共用配額，Embedding + Generate 合併計算)，非文檔宣稱的 100 RPM
> - 這是 429 頻繁觸發的根因
> - 35 RPM 保守值有效避免 429

---

## [2025-07-21] - NIM API 429 根因分析與修復 (CP-33)

### 根因
1. **限流器覆蓋範圍不足**：僅 `embed_and_store.py` 有限流器，查詢路徑 (`hybrid_search.py`, `generate_coding_suggestion.py`) 完全無限流
2. **配額共用錯誤假設**：原規劃 "Embedding 60 + Generate 30 = 90 RPM"，實際為帳號級共用 40 RPM
3. **Logger 未記錄 Header**：無法從歷史 log 還原真實配額使用情況

### 修復
1. 全局單例限流器 (35 RPM) 整合到查詢路徑 (`hybrid_search.py`, `generate_coding_suggestion.py`)
2. `nim_logger` 新增 `response_headers` 參數，自動過濾 rate/retry/limit/reset 相關 header
3. 429/503 最小等待保護 (10s)
4. 動態調整規則程式碼化 (`rate_limiter.py` 內建 `adjust_rpm`, `record_429`, `adjustment_history`)

---

## [2025-07-20] - CP-32 前端介面 + API 端點 + 啟動腳本

### 新增
- **`rag_ui.html`**：單一 HTML 雙擊即用查詢介面
  - Marked.js Markdown 渲染 (支援表格、程式碼區塊、引用)
  - 信心等級彩色標籤
  - 來源檔案可展開預覽
  - API endpoint 可在右上角修改並持久化到 localStorage
- **`ask.py`**：CLI 簡易查詢工具，自動 URL encode 中文
- **`start_rag.ps1` / `start_rag.sh`**：一鍵啟動腳本 (自動檢查 port、venv、.env)
- **`USAGE.md` / `QUICKSTART.md`**：完整使用說明

### API 端點
| 端點 | 方法 | 說明 |
|------|------|------|
| `/health` | GET | 健康檢查 |
| `/query` | GET/POST | 純檢索 (不生成) |
| `/suggest` | GET/POST | 完整建議 (檢索+重排+信心+生成) |
| `/suggest/timing` | GET | 完整建議 + 階段延遲 |
| `/suggest/stream` | GET | SSE 串流 (階段狀態 + token + 完整結果) |

---

## [2025-07-20] - CP-31 核心修復 (CORS/重試/索引路徑/導入路徑)

### 修復
- **POST 中文 body 亂碼**：`ask.py` 使用 `--data-binary @payload.json` 避免 Windows codepage 950 問題
- **索引路徑修正**：`BM25_INDEX_PATH` 指向 `data/processed/bm25_index.pkl`
- **導入路徑修正**：`hybrid_search.py` BASE_DIR 修正 (`parent.parent.parent.parent`)
- **重試邏輯統一**：429/503/timeout 統一指數退避 + 讀取 `Retry-After` header

---

## [2025-07-19] - CP-30 索引專案不匹配發現 (關鍵)

### 發現
- Chroma DB + BM25 索引的是 **`build_pyd/` 專案** (Python 推論代碼)
- 目標 GitLab Project 153 是 **`aaeonFramework/`** (C 驅動代碼)
- CP-21~CP-26 所有驗收數字 (72.2% 準確率、Faithfulness 0.45、provisional 門檻) **全部無效**

### 影響範圍
| CP | 受影響項目 |
|----|-----------|
| CP-11 | 索引建立時抓錯專案 |
| CP-12~15 | RRF+符號映射優化的是錯誤專案 |
| CP-16~20 | 生成整合測試針對錯誤專案 |
| CP-21~25 | 信心評估/門檻校準基於錯誤索引 |
| CP-26 | NIM Logger 記錄錯誤專案的查詢 |

### 狀態
🔄 **進行中**：需重建索引 (CP-30 進行中)

---

## [2025-07-18] - CP-26 NIM Logger (SQLite + JSONL)

### 新增
- `nim_logger.py`：SQLite + JSONL 雙重持久化
- 支援 4 種呼叫類型：`embedding` / `rerank` / `generate` / `evaluate_faithfulness`
- 記錄欄位：timestamp, query, model, call_type, request/response payload, fallback_flag, latency_ms, status_code, error
- `get_call_stats()` / `get_recent_calls()` 查詢介面

---

## [2025-07-17] - CP-24/25 Reranker + 信心評估

### 新增
- **Reranker** (`reranker.py`)：`nvidia/nemotron-3-ultra` 生成式重排序
- **信心評估** (`confidence_evaluator.py`)：`high/medium/low` 三級分級
- Provisional 門檻：基於 18 題小樣本 + 312 筆非均勻 log 校準

---

## [2025-07-16] - CP-21~23 Hybrid Search 優化

### 新增
- **RRF (Reciprocal Rank Fusion)** 取代加權融合
- **字符級 n-gram BM25** 解決中英混雜查詢
- **符號自動映射** (駝峰/底線拆分) 取代硬編碼字典

---

## [2025-07-15] - CP-11~13 索引建立 + ChromaDB

### 新增
- GitLab API 客戶端 (`gitlab_client.py`)
- 資料抓取 + 切分 (`fetch_and_save.py`, `chunking.py`)
- Embedding 批次寫入 ChromaDB (`embed_and_store.py`)
- 關鍵字索引 (`keyword_index.py`)

---

## 待辦 / 規劃中

| 項目 | 狀態 | 優先級 |
|------|------|--------|
| 重建 aaeonFramework 索引 (CP-30) | 🔄 進行中 | P0 |
| 降低 `max_tokens` (4096→1536) 減少 LLM 耗時 | 待辦 | P1 |
| 啟用 NIM Streaming 減少體感延遲 | 待辦 | P1 |
| 申請 NVIDIA 配額提升 (40→200 RPM) | 待辦 | P2 |
| 多 worker 部署 + Redis 分散式限流 | 規劃中 | P3 |

---

> **最後更新**：2025-07-21 11:30
> **維護者**：Hermes Agent + User