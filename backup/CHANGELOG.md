# Changelog - GitLab RAG MVP

本專案遵循 [Keep a Changelog](https://keepachangelog.com/) 格式。

## [Unreleased] - CP-25 進行中

### Added
- Golden Test Set (`src/gitlab_rag/golden_test_set.json`): 18 題評估案例 (8 CP-20 + 10 CP-22 清洗保留)，含 provenance (origin, label_quality, notes)
- Faithfulness 評估腳本 (`src/gitlab_rag/evaluate_faithfulness.py`): LLM-as-Judge (Nemotron-3-Ultra) on cached CP-20 generations
- CP-20 Faithfulness 基準分數 (8/8 題有效): 平均 0.597，分佈 0.15-1.00
- Low 信心門檻方案 (`src/gitlab_rag/low_confidence_threshold.py`): 連續分數 + 不確定性區間 (reranker median + MAD + RRF gap AND 邏輯)
- 校準後門檻值: LOW_THRESH=0.15, HIGH_THRESH=0.85, RRF_GAP_THRESH=0.15, MAD_THRESH=0.05

### Changed
- `golden_test_set.json`: cp22_010 "專案 設定 怎麼 測試 未知" 保持 low 標籤，註記 reranker median=0.9 爭議 (待真實查詢驗證)
- `confidence_evaluator.py`: 整合新門檻邏輯，保留向後相容
- `low_confidence_threshold.py`: **收緊 HIGH 判定邏輯** — HIGH 必須滿足 RRF gap > 0.15（核心訊號），移除 symbol_hits/vec_rank/bm25_rank 的獨立放行條件，5 題誤判 HIGH 修正為 MEDIUM

### Fixed
- Faithfulness prompt template 衝突修復: 改用 f-string 內插，避免 .format() 與 JSON schema {} 衝突
- MAD=0 假象修正: n=3 樣本 MAD 掩蓋離群值，改用全量樣本統計量 + bootstrap CI

### Verification (Final, CP-25 Step 2)
- 收緊邏輯後準確率: 13/18 = 72.2%（GPIO、available devices 因 RRF gap 極小判為 medium；cp22_010 保持 low 標籤並註記爭議；雲端 CI/CD、ML pytorch 邊界值誤判）
- 誠實暫定基準: 72.2%（非透過改標籤取得的虛高數字）

### Known Issue (待後續迭代解決)
- **GPIO / available devices 兩題**：RRF gap 極小（0.0005 / 0.0161），導致 HIGH→MEDIUM 誤判。內容核對發現：
  - GPIO：Top-1/2 均來自 `device_controll.py`，內容互補（高層方法 + 底層 EAPI 定義），屬「同一檔案多個相關片段」導致 RRF gap 小，非訊號弱
  - available devices：Top-1 來自錯誤檔案 (`device_controll.py` imports)，Top-2 才是正確答案 (`infer_base.py`)，RRF gap 小是因為 BM25 給錯誤檔案高分
- **建議例外規則**：若 Top-2 與 Top-1 內容高度相似（同檔案、語意互補），或 Top-2 為正確答案、Top-1 為干擾項，RRF gap 小不代表訊號弱。後續可引入「Top-2 內容相似度 / 語意互補度」檢查，作為 HIGH 判定的補充條件

## [v1.0.0-CP24] - 2026-07-16

### Added
- Reranker 整合 (`src/gitlab_rag/reranker.py`): Nemotron-3-Ultra 生成式重排序，串接於 hybrid_search 後
- 錯誤處理: 503/timeout fallback 到 RRF 排序，兩輪獨立隨機故障驗證
- API 日誌持久化 (`src/gitlab_rag/nim_logger.py`): SQLite + JSONL 雙重持久化

### Changed
- `confidence_evaluator.py`: 改為優先使用 rerank_score，回退到 rrf_score

### Fixed
- `fallback_triggered` 正確寫入 log schema (原本僅函式內層記錄，未同步上層決策)

## [v1.0.0-CP23] - 2026-07-15

### Added
- Query Expansion (`src/gitlab_rag/query_expander.py`): 純中文查詢擴展為英文技術術語
- camelCase 正則修復: `[a-z]+[A-Z][a-zA-Z]+` (原 `[a-z]+[A-Z][a-z]+` 過寬誤判 `whl` 等全小寫縮寫)

### Fixed
- 4 題基準查詢回歸測試 0/4 誤傷

## [v1.0.0-CP22] - 2026-07-14

### Added
- Low 信心路徑真實驗證: 28 low + 8 baseline 查詢，AUC=0.6352 (RRF)
- Reranker 上線後 AUC 提升至 0.97± (CP-24 後驗證)

### Changed
- 承認 low 信心分支在目前 corpus 規模下 AUC 不足，MVP 階段非阻塞

## [v1.0.0-CP21] - 2026-07-13

### Fixed
- POST 中文編碼根因: Windows codepage 950 + curl argv 路徑不相容
- 繞過方案: `printf > file` + `curl --data-binary @file`

### Added
- AGENTS.md 強制規則: POST 中文一律用檔案傳遞