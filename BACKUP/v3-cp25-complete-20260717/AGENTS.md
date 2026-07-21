# AGENTS.md — GitLab RAG 專案

## 專案概觀
GitLab code RAG 助手。檢索 → 信心評估 → NIM 生成 → 附來源。
FastAPI 對外服務，`/query`（純檢索）與 `/suggest`（含生成建議）並存。

**核心閉環模組**（CP-30 起，agent 每次修改前請先核對此清單與實際檔案結構
是否一致，有出入以實際掃描結果為準並回頭更新本節）：

```
查詢（Hermes Agent 呼叫）
  → query_expander.py        純中文查詢擴展（CP-23，跳過英文詞足夠的查詢）
  → hybrid_search.py         向量 + BM25 + symbol matching → RRF 融合
  → reranker.py               NIM nemotron-3-ultra 生成式重排序（CP-24）
  → confidence_evaluator.py   信心分級 high/medium/low（provisional 門檻，CP-25）
  → generate_coding_suggestion()   NIM 生成答案，附來源
```

支援模組：`nim_logger.py`（SQLite+JSONL 持久化，涵蓋 embedding/rerank/
generate/judge 四種呼叫）、`evaluate_faithfulness.py`（Faithfulness 評估，
支援多次取中位數）、`golden_test_set.json`（黃金測試集）、
`low_confidence_threshold.py`（low 門檻邏輯）。

## 驗收前必跑檢查
```bash
# 跑完整流程並印出 NIM 原始回應（含 finish_reason，勿只印解析後文字）
python generate_coding_suggestion.py

# 測 HTTP 端點（GET 與 POST 都要跑，含中文與純英文各一組）
curl -s "http://localhost:8000/suggest?question=<query>&top_k=5"
curl -s -X POST "http://localhost:8000/suggest" -H "Content-Type: application/json" --data-binary @payload.json

# 檢查檔案是否真的寫入
cat README.md | grep -A5 "六、執行進度"
cat ISSUES_LOG.md | tail -30

# 修改 .py 檔案後，驗證修改真的生效（Windows/MSYS 路徑常寫錯，見下方環境注意事項）
python -c "import <module>; import inspect; print(inspect.signature(<module>.<func>))"
```

## 回報規則（本專案最常出錯的地方）

**貼原始輸出，不要摘要。**
- ❌ `[來源 1] xxx.py - GPIO 相關內容`
- ✅ 直接貼 `suggestion` / API response 的完整原文字串，用 code block 包起來

**遇到指定方案失敗，先回報再換方案，不要靜默切換。**
- ❌ deepseek 額度用盡 → 自己默默換成別的模型 → 事後才提一句
- ✅ 「deepseek-v4-flash 額度用盡（附錯誤訊息），建議改用 X，是否同意？」等確認後再換

**每次生成呼叫都要留存可回溯的原始 log。**
- ❌ 只印 `result['suggestion']` 解析後的文字
- ✅ 印出 `model` / `finish_reason` / `completion_tokens`；若 `finish_reason == "length"` 自動加註截斷警告
- 涵蓋範圍：embedding / rerank / generate / **judge**（faithfulness 評審呼叫，
  CP-25 期間發現曾遺漏未接入 log，已補上，新增呼叫類型時比照辦理）

**用詞要對得上證據強度，不要用「已確認」代替「研判」。**
| 實際狀態 | 用詞 |
|---|---|
| 有原始 log 直接證實 | 已確認 |
| 邏輯合理但沒有直接證據 | 研判 / 推測 |
| 查不到、已放棄回溯 | 原因未明 |

**宣稱「已寫入檔案」時，附上寫入後重新讀取的內容，不要用同一份草稿充當兩種狀態。**

**規格要求 GET 和 POST 都測，就是兩個都要過，不能只過一個就把另一個歸類成「已知限制」帶過。**

**外部 API（NIM / GitLab）遇到 429 / 503，不可只靠「重試 N 次」硬闖。**
- ❌ 撞到 429 → 自行調大 retry 次數 → 繼續跑，沒有節流、沒有記錄
- ✅ 讀取回應標頭 `Retry-After`（若有）依時間等待；若無則用指數退避
  （2s → 4s → 8s），不可用固定間隔重試
- ✅ 批次任務（例如對 GitLab project 大量拉取 commit/issue）呼叫前先評估
  總請求量級，主動加入節流（固定間隔延遲），不要等撞到限制才處理
- ✅ 連續失敗達重試上限後，明確拋出可辨識錯誤（不可靜默吞掉），且這次
  失敗要被寫入 `nim_logger.py` 對應 log（`status_code` / `error` /
  `fallback_triggered`），比照 CP-24 fallback 曾被 log schema bug 靜默
  吞掉、事後才追查出來的教訓
- ✅ 先確認是哪一個 API（NIM 還是 GitLab）、目前呼叫頻率是否真的必要，
  回報診斷結果、等確認方案後才調整程式碼，不要自己默默改重試次數了事

## 邊界
- 不寫死 API 金鑰，一律走 `.env`
- 不修改 `/query` 既有行為，新功能只能新增端點
- 每個 CP 完成後停止回報，不可在測試未跑完時送出「驗收完成」

## 環境注意事項
- Windows/MSYS 下寫檔案工具曾多次將路徑誤寫為 `C:\c\Users\...`（多一層
  `\c\`），與 Python 實際 import 路徑不一致，改完 `.py` 檔案務必用上方
  簽名驗證指令確認修改真的生效，不能只憑「寫入成功」的訊息就假設完成
- POST body 含中文一律用 `printf > file` + `curl --data-binary @file`，
  不可直接在命令列參數帶中文（Windows codepage 950/Big5 轉碼問題，CP-21）

## 已知限制（Known Issues，持續更新，非阻塞項目）
- `available devices list` 查詢：BM25 給不相關檔案高分、Top-1 為干擾項，
  屬檢索排序品質問題，非信心閾值問題，待排查根因
- Low 信心門檻為 provisional 值，基於 18 題小樣本+312 筆非均勻累積 log
  校準，待接入真實查詢流量後需重新校準（見 CP-30）
- 「建立 whl 安裝包」「危險區域」兩題 Faithfulness 評審僅 2/3 有效，
  待補跑第三次

## 詳細踩雷案例
CP-16~CP-26 執行過程的完整案例紀錄，見企劃書「執行歷程與已知限制」章節，
不重複收錄於此。
