# Changelog - GitLab RAG MVP

本專案遵循 [Keep a Changelog](https://keepachangelog.com/) 格式。

## [Unreleased] - CP-25 Step 3 完成

### Added
- Faithfulness 多次評審取中位數：`evaluate_faithfulness.py` 支援 `--n-runs` (預設 3)，輸出 median/MAD/n_valid
- 完整 18 題 Faithfulness 基準 (`cp25_faithfulness_baseline_v2.json`)：含分佈、中位數、MAD、n_valid
- `call_nim_judge` 接上 `nim_logger` (CP-26 補漏)：call_type="evaluate_faithfulness"，記錄 timestamp/query/model/status_code/error/fallback_triggered/latency_ms/finish_reason
- `n_valid_per_query` 欄位：逐題記錄有效評審次數（17 題 3/3 或 2/3，1 題 1/3）
- Limitations 區新增：`non_deterministic` (5-6 倍極端離散、MAD 掩蓋風險)、`sample_size_variation` (n_valid=1 題目未混入整體統計)

### Changed
- `evaluate_faithfulness.py`：`call_nim_judge` 內建 `log_nim_call`，符合 CP-26 記錄規範
- Step 1 vs Step 3 對照表措辭修正：「個別題目雙向波動 ±0.4，中位數提供更穩定估計」，不再宣稱「系統性向上偏差」

### Fixed
- 發現 CP-26 log 覆蓋缺口：54 次 judge 呼叫未接上 nim_logger，現已補齊

### Verification (CP-25 Step 3 Final)
- 18 題 n_valid 清單：14 題 3/3、3 題 2/3、1 題 1/3
- **n_valid ≥ 2 (17 題)**：平均 Faithfulness = 0.4669，整體中位數 = 0.5000
- **n_valid = 1 (1 題)**：react vue angular 前端 = 0.1667（單獨列出，未混入主統計）
- 原報告整體平均 0.4502（含 n_valid=1）→ 修正後主基準 0.4669
- 危險區域 0.400 vs 0.071 (5.6 倍離散，MAD=0.164) 確認為完整有效評審非 parse 失敗

### Known Issue (CP-25 遺留)
- LLM-as-Judge 極端非確定性：同一答案三次評審可達 5-6 倍差距，MAD 單值無法完整反映風險；建議後續 n_runs=5 或多模型評審
- n_valid=1 的題目 (react vue angular 前端) 受限於 timeout，無法取得 3 次穩定樣本

---

## [v1.0.0-CP24] - 2026-07-16

### Added
- Reranker 整合 (`src/gitlab_rag/reranker.py`): Nemotron-3-Ultra 生成式重排序，串接於 hybrid_search 後
- 錯誤處理: 503/timeout fallback 到 RRF 排序，兩輪獨立隨機故障驗證
- API 日誌持久化 (`src/gitlab_rag/nim_logger.py`): SQLite + JSONL 雙重持久化

### Changed
- `confidence_evaluator.py`: 改為優先使用 rerank_score，回退到 rrf_score

### Fixed
- `fallback_triggered` 正確寫入 log schema (原本僅函式內層記錄，未同步上層決策)

---

## [v1.0.0-CP23] - 2026-07-15

### Added
- Query Expansion (`src/gitlab_rag/query_expander.py`): 純中文查詢擴展為英文技術術語
- camelCase 正則修復: `[a-z]+[A-Z][a-zA-Z]+` (原 `[a-z]+[A-Z][a-z]+` 過寬誤判 `whl` 等全小寫縮寫)

### Fixed
- 4 題基準查詢回歸測試 0/4 誤傷

---

## [v1.0.0-CP22] - 2026-07-14

### Added
- Low 信心路徑真實驗證: 28 low + 8 baseline 查詢，AUC=0.6352 (RRF)
- Reranker 上線後 AUC 提升至 0.97± (CP-24 後驗證)

### Changed
- 承認 low 信心分支在目前 corpus 規模下 AUC 不足，MVP 階段非阻塞

---

## [v1.0.0-CP21] - 2026-07-13

### Fixed
- POST 中文編碼根因: Windows codepage 950 + curl argv 路徑不相容
- 繞過方案: `printf > file` + `curl --data-binary @file`

### Added
- AGENTS.md 強制規則: POST 中文一律用檔案傳遞