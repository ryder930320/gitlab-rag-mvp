# GitLab RAG 系統完整使用手冊

> **專案版本**：CP-32 完成版  
> **最後更新**：2026-07-20  
> **適用環境**：Windows/MSYS2, Python 3.11+, NVIDIA NIM API

---

## 目錄
1. [系統概覽](#系統概覽)
2. [專案架構與資料夾說明](#專案架構與資料夾說明)
3. [環境安裝與設定](#環境安裝與設定)
4. [核心模組說明](#核心模組說明)
5. [資料流程圖](#資料流程圖)
6. [使用指南：從零開始](#使用指南從零開始)
7. [日常操作指令](#日常操作指令)
8. [API 端點說明](#api-端點說明)
9. [評估與驗證流程](#評估與驗證流程)
10. [常見問題與除錯](#常見問題與除錯)
11. [開發規範與 Checkpoint 機制](#開發規範與-checkpoint-機制)

---

## 系統概覽

### 是什麼
GitLab Code RAG (Retrieval-Augmented Generation) 系統，專為 **AAEON Framework (GitLab Project 153)** 設計的程式碼智能問答助手。

### 核心能力
| 能力 | 說明 |
|------|------|
| **跨語言檢索** | 中文查詢 → 英文 C/C++ 程式碼 (字符級 3-gram + 查詢擴展) |
| **混合檢索** | 向量 (nv-embedqa-e5-v5) + BM25 + 符號匹配 → RRF 融合 |
| **生成式重排序** | Nemotron-3-Ultra 生成式重排序 (CP-24) |
| **信心分級** | High / Medium / Low 三級信心評估 (CP-17, CP-25) |
| **生成建議** | 含來源引用的程式碼建議生成 (Nemotron-3-Ultra) |
| **完整追蹤** | 所有 NIM 呼叫記錄 SQLite + JSONL (CP-26) |

### 技術棧
- **Embedding**: `nvidia/nv-embedqa-e5-v5` (1024-dim)
- **Generation/Rerank**: `nvidia/nemotron-3-ultra-550b-a55b`
- **Vector DB**: ChromaDB (PersistentClient)
- **BM25**: 字符級 3-gram 自實作
- **API**: FastAPI + Uvicorn
- **記錄**: SQLite + JSONL 雙寫

---

## 專案架構與資料夾說明

```
gitlab-rag-mvp/
├── .env                    # 環境變數 (NIM_API_KEY, GITLAB_URL, GITLAB_TOKEN, GITLAB_PROJECT)
├── .env.example            # 環境變數範本
├── requirements.txt        # Python 依賴
├── MANUAL.md               # 本手冊
├── README.md               # 專案簡介
├── AGENTS.md               # Agent 開發規範
├── ISSUES_LOG.md           # 問題追蹤總表
├── CHANGELOG.md            # 版本變更記錄
│
├── src/                    # === 核心原始碼 ===
│   └── gitlab_rag/
│       ├── __init__.py
│       ├── api/            # HTTP 介面層
│       │   └── app.py      # FastAPI app: /query, /suggest, /health
│       ├── core/           # 核心檢索生成管線
│       │   ├── hybrid_search.py          # RRF 混合檢索 (向量+BM25+符號)
│       │   ├── generate_coding_suggestion.py  # 端到端生成
│       │   ├── confidence_evaluator.py   # 信心分級
│       │   ├── rag_interface.py          # 對外介面 query_gitlab_context()
│       │   ├── prompt_builder.py         # Prompt 組裝
│       │   ├── symbol_expansion.py       # 符號 token 抽取
│       │   ├── query.py                  # 查詢擴展入口
│       │   └── nim_logger.py             # NIM 呼叫記錄
│       ├── data_ingestion/   # 資料攝取管線
│       │   ├── gitlab_client.py          # GitLab REST API 客戶端
│       │   ├── fetch_and_save.py         # 抓取 commits/files
│       │   ├── chunking.py               # 程式碼分塊
│       │   ├── chunking_v2.py            # 實驗性分塊
│       │   ├── embed_and_store.py        # Embedding → ChromaDB
│       │   └── keyword_index.py          # BM25 索引建立
│       ├── evaluation/       # 評估模組
│       │   └── cp10_vs_cp12.py
│       ├── cp30/             # CP-30 歷史資料挖掘 (預留)
│       ├── golden_test_set.json          # 黃金測試集
│       └── query_expansion/              # 查詢擴展 (CP-23, 已整合至 core/)
│
├── scripts/                  # === 執行腳本 (按 CP 階段分類) ===
│   ├── cp30/                 # CP-30 歷史資料挖掘
│   │   ├── cp30_a_full_scan.py
│   │   ├── cp30_a_inventory.py
│   │   ├── cp30_b_build_testset.py
│   │   ├── cp30_c_eval_optimized.py
│   │   ├── cp30_c_evaluate.py
│   │   └── cp30_c_run_evaluation.py
│   ├── eval/                 # 評估腳本
│   │   ├── cp25/
│   │   └── cp30/
│   ├── ingestion/            # 資料攝取腳本 (預留)
│   ├── maintenance/          # 維護腳本 (預留)
│   ├── utils/                # 工具腳本 (預留)
│   └── verify/               # 驗證腳本 (預留)
│
├── data/                     # === 資料層 (依生命週期分層) ===
│   ├── nim_calls.db          # NIM 呼叫記錄 SQLite
│   ├── nim_calls.jsonl       # NIM 呼叫記錄 JSONL
│   ├── raw/                  # 原始資料 (GitLab API 直存)
│   │   ├── raw_commits.json
│   │   └── raw_files.json
│   ├── processed/            # 處理後可直接檢索
│   │   ├── chunks.json       # 分塊文檔 (含 metadata)
│   │   ├── chunks_v2.json
│   │   ├── bm25_index.pkl    # BM25 索引
│   │   ├── embedding_progress.json
│   │   ├── cp30_a_inventory.json
│   │   ├── cp30_c_results.json
│   │   └── gitlab_historical_test_set.json
│   ├── evaluation/           # 評估基準
│   │   ├── cp25_faithfulness_baseline.json
│   │   ├── cp25_faithfulness_baseline_v2.json
│   │   └── test_results_full.json
│   ├── evaluation_logs/      # 評估過程記錄
│   │   └── rerank_verification_*.json
│   ├── cache/                # 快取/備份
│   │   ├── bm25_index.pkl.backup_build_pyd_20260717_154908
│   │   └── cp30_diffs/       # 604 個 commit diff 快取
│   └── outputs/              # 執行輸出
│
├── chroma_db/                # ChromaDB 持久化向量資料庫
├── chroma_db.backup_build_pyd_20260717_154908/  # 備份索引
│
├── config/                   # 設定檔 (預留)
├── docs/                     # 文件 (預留)
├── tests/                    # 單元測試 (預留)
│
└── BACKUP/                   # 歷史版本備份 (不可修改)
    ├── v3-cp25-complete-20260717/
    ├── gitlab-rag-mvp-cp12-15-v1.0/
    ├── gitlab-rag-mvp-cp20/
    └── ...
```

---

## 環境安裝與設定

### 1. 前置需求
```bash
# Python 3.11+ (建議使用 uv 或 venv)
python -m venv .venv
source .venv/bin/activate  # MSYS2: source .venv/Scripts/activate

# 安裝依賴
pip install -r requirements.txt
```

### 2. 環境變數設定 (`.env`)
```ini
# NVIDIA NIM API (必填)
NIM_API_KEY=nvapi-xxxxxxxxxxxxxxxxxxxxxxxx
NIM_EMBED_MODEL=nvidia/nv-embedqa-e5-v5
NIM_GENERATE_MODEL=nvidia/nemotron-3-ultra-550b-a55b

# GitLab (資料攝取時必填)
GITLAB_URL=https://sts.aaeon.com.tw:11180
GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx
GITLAB_PROJECT=153  # AAEON Framework

# 可選：ChromaDB 路徑
CHROMA_DIR=./chroma_db
```

### 3. 依賴套件 (`requirements.txt` 關鍵項)
```
chromadb==0.4.24
httpx==0.27.0
fastapi==0.111.0
uvicorn==0.30.1
python-dotenv==1.0.1
rank-bm25==0.2.2
numpy==1.26.4
pydantic==2.7.4
```

---

## 核心模組說明

### 1. 混合檢索 `hybrid_search.py`
```python
# 入口函數
def hybrid_search(question: str, top_k: int = 5) -> List[Dict]:
    """
    輸入: 查詢字串
    輸出: List[Dict] 包含:
        - content, file_path, source_type, language
        - chunk_index, created_at
        - score (RRF), score_vector, score_bm25
        - rrf_score, vec_rank, bm25_rank, symbol_hits
    """
```

**三路融合邏輯**:
1. **向量檢索**: ChromaDB `nv-embedqa-e5-v5` (input_type=query)
2. **BM25 檢索**: 字符級 3-gram (內容 + 符號 + 檔名)
3. **符號匹配**: camelCase/snake_case token 交集
4. **RRF 融合**: `score = Σ 1/(k + rank)` , k=60

### 2. 端到端生成 `generate_coding_suggestion.py`
```python
def generate_coding_suggestion(question: str, top_k: int = 5) -> Dict:
    """
    完整流程: 機率: hybrid_search → confidence_evaluator → prompt_builder → NIM generate
    回傳:
        {
            "suggestion": str,           # 生成建議
            "confidence": "high|medium|low",
            "confidence_reason": str,
            "sources": List[Dict],       # 來源片段
            "error": str | None          # 生成失敗時的錯誤
        }
    """
```

**重試邏輯** (統一速率限制處理):
- 429: 讀取 `Retry-After`，指數退避 (10s, 20s, 40s)
- 503: 指數退避 (10s, 20s, 40s)
- Timeout: 指數退避
- 非重試類錯誤 (402, 400, 500 等): 直接拋出

### 3. 信心評估 `confidence_evaluator.py`
```python
def evaluate_confidence(retrieved_chunks: List[Dict]) -> Dict:
    """
    規則 (Provisional, CP-25):
    - High: Top-1/Top-2 RRF gap > 20%
    - Low: symbol_hits=0 AND vec_rank>5 AND bm25_rank>8
    - Medium: 其他
    """
```

### 4. NIM 記錄器 `nim_logger.py`
```python
# 記錄所有 NIM 呼叫
log_nim_call(
    call_type: "embedding|rerank|generate|evaluate_faithfulness",
    model: str,
    request_payload: dict,
    response_payload: dict | None,
    query: str,
    fallback_triggered: bool,
    latency_ms: int,
    status_code: int,
    error: str
)
```
**輸出**: `data/nim_calls.db` (SQLite) + `data/nim_calls.jsonl` (JSONL)

### 5. 資料攝取管線 `data_ingestion/`
| 腳本 | 功能 | 輸出 |
|------|------|------|
| `gitlab_client.py` | GitLab API 客戶端 (分頁、速率限制) | - |
| `fetch_and_save.py` | 抓取專案檔案/Commits | `data/raw/raw_files.json`, `raw_commits.json` |
| `chunking.py` | 程式碼語義分塊 (保留函數/類別完整性) | `data/processed/chunks.json` |
| `embed_and_store.py` | Embedding 寫入 ChromaDB | `chroma_db/` |
| `keyword_index.py` | 建立 BM25 + 符號索引 | `data/processed/bm25_index.pkl` |

---

## 資料流程圖

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  GitLab     │────▶│  fetch_and_  │────▶│  data/raw/  │
│  Project 153│     │  save.py     │     │  *.json     │
└─────────────┘     └──────────────┘     └──────┬──────┘
                                                 │
                    ┌──────────────┐             │
                    │  chunking.py │◀────────────┘
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐     ┌──────────────────┐
                    │ embed_and_   │────▶│   chroma_db/     │
                    │ store.py     │     │  (向量索引)       │
                    └──────┬───────┘     └──────────────────┘
                           │
                    ┌──────▼───────┐     ┌──────────────────┐
                    │ keyword_     │────▶│ data/processed/  │
                    │ index.py     │     │ bm25_index.pkl   │
                    └──────────────┘     └──────────────────┘
                           │
                    ┌──────▼───────┐     ┌──────────────────┐
                    │ hybrid_      │────▶│ 檢索結果 (RRF)   │
                    │ search.py    │     └────────┬─────────┘
                    └──────┬───────┘              │
                           │                      ▼
                    ┌──────▼───────┐     ┌──────────────────┐
                    │ confidence_  │────▶│ High/Medium/Low  │
                    │ evaluator.py │     └────────┬─────────┘
                    └──────┬───────┘              │
                           │                      ▼
                    ┌──────▼───────┐     ┌──────────────────┐
                    │ prompt_      │────▶│ 組裝 Prompt      │
                    │ builder.py   │     └────────┬─────────┘
                    └──────┬───────┘              │
                           │                      ▼
                    ┌──────▼───────┐     ┌──────────────────┐
                    │ NIM Generate │────▶│ 建議 + 來源引用   │
                    │ (Nemotron)   │     └──────────────────┘
                    └──────────────┘
                           │
                    ┌──────▼───────┐
                    │ nim_logger   │────▶ nim_calls.db + nim_calls.jsonl
                    │ .py          │
                    └──────────────┘
```

---

## 使用指南：從零開始

### 步驟 1：環境準備
```bash
cd gitlab-rag-mvp
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 編輯 .env 填入 NIM_API_KEY, GITLAB_TOKEN 等
```

### 步驟 2：資料攝取 (首次或重建索引)
```bash
# 1. 驗證 GitLab 連線
python -m src.gitlab_rag.data_ingestion.gitlab_client

# 2. 抓取專案檔案與 Commits
python -m src.gitlab_rag.data_ingestion.fetch_and_save

# 3. 程式碼分塊
python -m src.gitlab_rag.data_ingestion.chunking

# 4. Embedding 寫入 ChromaDB (耗時最久，約 10-30 分鐘)
python -m src.gitlab_rag.data_ingestion.embed_and_store

# 5. 建立 BM25 + 符號索引
python -m src.gitlab_rag.data_ingestion.keyword_index
```

> **注意**：若需重建，先備份並刪除 `chroma_db/`, `data/processed/bm25_index.pkl`

### 步驟 3：啟動 API 服務
```bash
# 開發模式 (含熱重載)
uvicorn src.gitlab_rag.api.app:app --reload --port 8000

# 生產模式
uvicorn src.gitlab_rag.api.app:app --host 0.0.0.0 --port 8000 --workers 4
```

### 步驟 4：測試查詢
```bash
# 健康檢查
curl http://localhost:8000/health

# 純檢索端點 (支援中文 GET)
curl "http://localhost:8000/query?question=GPIO%E6%8E%A7%E5%88%B6%E6%80%8E%E9%BA%BC%E7%94%A8%EF%BC%9F&top_k=5"

# 生成建議端點 (中文請用 GET 或檔案 POST)
curl "http://localhost:8000/suggest?question=GPIO控制怎麼用？&top_k=5"

# POST 範例 (中文需用檔案避免 MSYS 編碼問題)
printf '{"question":"如何建立 whl 安裝包？","top_k":5}' > payload.json
curl -X POST http://localhost:8000/suggest \
  -H "Content-Type: application/json" \
  --data-binary @payload.json
```

### 步驟 5：Python 直接呼叫
```python
from src.gitlab_rag.core.rag_interface import query_gitlab_context
from src.gitlab_rag.core.generate_coding_suggestion import generate_coding_suggestion

# 純檢索
results = query_gitlab_context("GPIO 控制怎麼用？", top_k=5, use_hybrid=True)

# 完整生成
result = generate_coding_suggestion("如何設定裝置？", top_k=5)
print(result["confidence"])
print(result["suggestion"])
for src in result["sources"]:
    print(f"  [{src['source_id']}] {src['file_path']} chunk#{src['chunk_index']}")
```

---

## 日常操作指令

### 檢索測試
```bash
# 單次查詢測試 (列出 Top-5 詳細資訊)
python -c "
from src.gitlab_rag.core.hybrid_search import hybrid_search
for r in hybrid_search('available devices list', top_k=5):
    print(f\"{r['rrf_score']:.4f} | vec={r['vec_rank']} bm25={r['bm25_rank']} sym={r['symbol_hits']} | {r['file_path']}\")
"
```

### 信心評估測試
```bash
python -c "
from src.gitlab_rag.core.hybrid_search import hybrid_search
from src.gitlab_rag.core.confidence_evaluator import evaluate_confidence

for q in ['GPIO 控制怎麼用？', 'available devices list', '建立 whl 安裝包']:
    results = hybrid_search(q, top_k=5)
    conf = evaluate_confidence(results)
    print(f'{q}: {conf[\"level\"]} - {conf[\"reason\"]}')
"
```

### 完整生成測試
```bash
python -m src.gitlab_rag.core.generate_coding_suggestion
```

### 查看 NIM 呼叫統計
```bash
python -c "
from src.gitlab_rag.core.nim_logger import get_call_stats
import json
print(json.dumps(get_call_stats(), indent=2, ensure_ascii=False))
"
```

### 查看最近呼叫記錄
```bash
python -c "
from src.gitlab_rag.core.nim_logger import get_recent_calls
import json
for r in get_recent_calls(10, 'generate'):
    print(f\"{r['timestamp']} | {r['status_code']} | fb={r['fallback_triggered']} | {r['latency_ms']}ms | {r['error'][:60]}\")
"
```

### 重建索引 (切換專案或資料更新)
```bash
# 1. 備份現有索引
mv chroma_db chroma_db.backup_$(date +%Y%m%d_%H%M%S)
mv data/processed/bm25_index.pkl data/processed/bm25_index.pkl.backup

# 2. 修改 .env 中的 GITLAB_PROJECT

# 3. 重新執行步驟 2 的 1-5
```

---

## API 端點說明

### 基礎端點
| 端點 | 方法 | 說明 |
|------|------|------|
| `/health` | GET | 健康檢查，回傳 `{status: "ok"}` |
| `/query` | GET/POST | 純檢索，回傳檢索片段列表 |
| `/suggest` | GET/POST | 完整生成建議，含信心等級與來源 |

### `/query` 參數
| 參數 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `question` | string | 必填 | 查詢字串 |
| `top_k` | int | 5 | 回傳筆數 |
| `use_hybrid` | bool | true | 是否使用混合檢索 |

### `/suggest` 參數
| 參數 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `question` | string | 必填 | 查詢字串 |
| `top_k` | int | 5 | 檢索筆數 |

### 回傳格式
```json
// /query 回傳
{
  "results": [
    {
      "content": "...",
      "file_path": "aaeonFramework/EC.c",
      "source_type": "code",
      "language": "c",
      "chunk_index": 12,
      "score": 0.0156,
      "score_vector": 0.8234,
      "score_bm25": 1234.5,
      "rrf_score": 0.0156,
      "vec_rank": 3,
      "bm25_rank": 1,
      "symbol_hits": 2
    }
  ]
}

// /suggest 回傳
{
  "suggestion": "根據 [來源 1] 的 EC.c 中 ECWriteByte 函數...",
  "confidence": "high",
  "confidence_reason": "Top-1 RRF 分數 (0.0156) 明顯領先 Top-2 (0.0123)，差距 21.2%",
  "sources": [
    {
      "source_id": 1,
      "file_path": "aaeonFramework/EC.c",
      "chunk_index": 12,
      "preview": "NTSTATUS ECWriteByte(...)",
      "rrf_score": 0.0156,
      "symbol_hits": 2
    }
  ],
  "error": null
}
```

### 中文查詢注意事項 (Windows/MSYS)
- **GET 請求**：URL 自動編碼，直接可用
- **POST 請求**：需用檔案傳遞避免編碼問題
  ```bash
  printf '{"question":"中文查詢"}' > payload.json
  curl -X POST http://localhost:8000/suggest -H "Content-Type: application/json" --data-binary @payload.json
  ```

---

## 評估與驗證流程

### CP-30 歷史資料驗證 (130 題)
```bash
# 執行完整評估 (需先建立測試集)
python scripts/cp30/cp30_c_run_evaluation.py

# 或使用優化版
python scripts/cp30/cp30_c_eval_optimized.py
```

**關鍵指標**:
- Overall Top-3 Hit Rate: **89.2%** (116/130, 扣除 8 errors)
- 明確技術修復類 (9 題): **100%**
- 純功能支援類 (121 題): **88.4%**

### 信心分級驗證
```bash
python -c "
from src.gitlab_rag.core.hybrid_search import hybrid_search
from src.gitlab_rag.core.confidence_evaluator import evaluate_confidence

# 9 題明確技術修復查詢
tech_fix_queries = [...]
for q in tech_fix_queries:
    results = hybrid_search(q, top_k=5)
    conf = evaluate_confidence(results)
    print(f'{q[:40]}: {conf[\"level\"]} - {conf[\"reason\"]}')
"
```

### Faithfulness 評估 (CP-25)
```bash
python -m src.gitlab_rag.evaluation.evaluate_faithfulness --n-runs 3
```

---

## 常見問題與除錯

### 1. NIM API 429/503/Timeout
**現象**: 大量查詢時出現速率限制或服務不可用
**解決**:
- 程式碼內建指數退避重試 (10s→20s→40s)
- 批次查詢加入 `time.sleep(0.5)` 節流
- 確認 `.env` 中 `NIM_API_KEY` 有效且有額度

### 2. ChromaDB 併發錯誤
**現象**: `Could not connect to tenant`, `RustBindingsAPI` 屬性錯誤
**解決**:
- 程式碼已加入單例連線池 + 指數退避重試 (CP-31)
- 若持續發生：降低並發 worker 數

### 3. BM25 分數異常高 (干擾項排在前面)
**現象**: `available devices list` 查詢 Top-1 為無關檔案
**原因**: 字符級 3-gram 產生極稀有 tokens (如 `vai`, `ila`)，IDF 極高
**狀態**: 已記錄於 ISSUES_LOG.md 已知限制，屬 Tokenization/IDF 根因

### 4. Low 信心門檻從未觸發
**現象**: 130 題測試中 0 題觸發 Low
**原因**: Corpus 結構導致 vec_rank/BM25_rank 都不會同時很差
**狀態**: Provisional 門檻待真實流量重新校準 (CP-30-D)

### 5. Windows POST 中文 400 錯誤
**解決**: 使用 GET 查詢參數 或 `printf > payload.json` + `--data-binary @payload.json`

### 6. 模組導入失敗 (Windows 路徑問題)
**現象**: 改檔案後 import 仍舊代碼
**檢查**: `python -c "import src.gitlab_rag.core.hybrid_search; import inspect; print(inspect.getfile(src.gitlab_rag.core.hybrid_search))"`
**原因**: `write_file` 可能寫入 `C:\c\Users\...` 而 Python 從 `C:\Users\...` 讀取

---

## 開發規範與 Checkpoint 機制

### Checkpoint 流程 (不可省略)
| CP | 階段 | 驗收標準 |
|----|------|----------|
| CP-1 | 專案骨架+依賴 | 資料夾結構、venv、requirements.txt、.env.example、.gitignore |
| CP-2 | 資料攝取 | GitLab API 連線、檔案列表、Commit 抓取、樣本內容 |
| CP-3 | 原始資料持久化 | JSON 檔寫入、Schema 驗證、非零筆數 |
| CP-4 | 分塊 | 筆數符合預期、Overlap 驗證、無中斷函數 |
| CP-5 | Embedding+向量庫 | 維度正確、筆數匹配、重試邏輯可用 |
| CP-6 | 檢索測試 | 5+ 查詢、≥3/5 相關、Top-k 非空 |
| CP-7 | API 介面 | 本地函數 + FastAPI 同工不同源、簽名穩定 |

**鐵律**: **每個 CP 完成必須停下回報，等待人工確認才能進入下一階段**

### 程式碼規範
1. **所有 NIM 呼叫必須經過 `nim_logger.log_nim_call()`**
2. **速率限制統一處理**: 讀取 `Retry-After` → 指數退避 (2→4→8s)
3. **錯誤不靜默吞掉**: 非重試類錯誤直接拋出 RuntimeError
4. **中文查詢**: GET 端點支援，POST 需檔案傳遞
5. **用詞精確**: 已確認/研判/原因未明，不可混用

### Git 規範
```bash
# 提交前檢查
git status
git diff

# 提交訊息格式
git commit -m "feat(cp32): add fallback verification for 429/503/timeout

- hybrid_search.py: add 503/timeout retry with fallback logging
- generate_coding_suggestion.py: unified retry logic
- nim_logger: record fallback_triggered for all retry paths

CP-32-A verified: fallback path tested with mock 429/503/timeout"
```

### 文件同步更新 (修改代碼後必做)
- `README.md`: 六、執行進度與成果
- `AGENTS.md`: 核心閉環模組、驗收前必跑檢查
- `ISSUES_LOG.md`: 新問題記錄
- `CHANGELOG.md`: 版本變更記錄

---

## 版本歷程

| 版本 | 日期 | 關鍵里程碑 |
|------|------|------------|
| v1.0-mvp | 2026-07-15 | CP-07 純向量基線完成 |
| v1.0-hybrid | 2026-07-16 | CP-11 RRF 混合檢索完成 |
| v2.0-techdebt | 2026-07-17 | CP-15 技術債清理 (RRF+符號自動映射) |
| v3.0-generation | 2026-07-18 | CP-20 生成整合完成 (/suggest 端點) |
| v3.0-cp25 | 2026-07-19 | CP-25 評估框架 (Faithfulness median-of-3 + Low 門檻) |
| v3.0-cp30 | 2026-07-20 | **CP-30 歷史資料挖掘完成** (130 題驗證、索引重建、Chroma 併發修復、NIM Logger 整合) |
| v3.0-cp32 | 2026-07-20 | **CP-32 補強完成** (Fallback 驗證、BM25 根因、Low 門檻敏感度、文件一致性) |

---

## 附錄：關鍵檔案快速索引

| 功能 | 檔案路徑 |
|------|----------|
| 環境變數 | `.env` / `.env.example` |
| 依賴套件 | `requirements.txt` |
| FastAPI 入口 | `src/gitlab_rag/api/app.py` |
| 混合檢索核心 | `src/gitlab_rag/core/hybrid_search.py` |
| 端到端生成 | `src/gitlab_rag/core/generate_coding_suggestion.py` |
| 信心評估 | `src/gitlab_rag/core/confidence_evaluator.py` |
| NIM 記錄器 | `src/gitlab_rag/core/nim_logger.py` |
| 查詢介面 | `src/gitlab_rag/core/rag_interface.py` |
| 資料攝取總入口 | `scripts/cp30/cp30_a_full_scan.py` |
| 評估腳本 | `scripts/cp30/cp30_c_eval_optimized.py` |
| NIM 呼叫記錄 (DB) | `data/nim_calls.db` |
| NIM 呼叫記錄 (JSONL) | `data/nim_calls.jsonl` |
| ChromaDB 向量庫 | `chroma_db/` |
| BM25 索引 | `data/processed/bm25_index.pkl` |
| 分塊文檔 | `data/processed/chunks.json` |

---

> **維護者提醒**：本系統在 **NVIDIA NIM 免費額度** 下運行，Nemotron-3-Ultra 為當前配額下最穩定模型。若額度政策變更，需重新評估模型選型 (參考 CP-18 決策記錄)。所有 Checkpoint 驗收紀錄見 `ISSUES_LOG.md` 及各 CP 階段文件。