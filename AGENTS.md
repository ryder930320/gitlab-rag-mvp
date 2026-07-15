# AGENTS.md — GitLab RAG 專案

## 專案概觀
GitLab code RAG 助手。檢索 → 信心評估 → NIM 生成 → 附來源。
FastAPI 對外服務，`/query`（純檢索）與 `/suggest`（含生成建議）並存。

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

**用詞要對得上證據強度，不要用「已確認」代替「研判」。**
| 實際狀態 | 用詞 |
|---|---|
| 有原始 log 直接證實 | 已確認 |
| 邏輯合理但沒有直接證據 | 研判 / 推測 |
| 查不到、已放棄回溯 | 原因未明 |

**宣稱「已寫入檔案」時，附上寫入後重新讀取的內容，不要用同一份草稿充當兩種狀態。**

**規格要求 GET 和 POST 都測，就是兩個都要過，不能只過一個就把另一個歸類成「已知限制」帶過。**

## 邊界
- 不寫死 API 金鑰，一律走 `.env`
- 不修改 `/query` 既有行為，新功能只能新增端點
- 每個 CP 完成後停止回報，不可在測試未跑完時送出「驗收完成」

## 詳細踩雷案例
CP-16~CP-20 執行過程的完整案例紀錄，見企劃書「執行歷程與已知限制」章節，不重複收錄於此。