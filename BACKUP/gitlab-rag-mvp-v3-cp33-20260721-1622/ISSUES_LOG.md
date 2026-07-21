# GitLab RAG 專案問題紀錄總表 (ISSUES_LOG.md)

> 記錄所有開發階段遇到的問題、分析與解決方案，**每個問題標註解決狀態**

---

## ❌ 關鍵問題：索引專案不匹配（嚴重影響 CP-21~26 所有驗收結論）

**解決狀態：🔄 進行中 (CP-30 發現，正在重建索引)**

### 現象
- CP-30-A 盤點 GitLab Project 153 (aaeonFramework) 時發現：Chroma DB 與 BM25 索引內容為 `build_pyd/` 專案（Python AI 推論程式碼：device_controll.py, infer_base.py 等）
- GitLab Project 153 實際為 `aaeonFramework/`（C 語言驅動專案：.c, .h, .inf 檔案）
- CP-30-C 用 130 題真實問題（源自 aaeonFramework）跑驗證，Top-3 命中率 ~0%，Confidence 全為 medium

### 根因分析
| 層面 | 說明 |
|------|------|
| 索引來源錯誤 | CP-11 (2026-07-15) 建立索引時，.env 中的 GITLAB_PROJECT 設定錯誤或未生效，導致 fetch_and_save.py 抓取的不是 Project 153 |
| 無驗證機制 | CP-11~CP-26 全程未對照「索引內容是否對應目標 GitLab 專案」做驗收檢查 |
| 測試題構造偏差 | CP-6 起的 18~32 題構造測試題（GPIO、whl、available devices 等），皆是針對 build_pyd/ 專案內容設計，與 aaeonFramework 完全無關 |
| 驗收數字失真 | CP-25 Step 2 的 72.2% 準確率、Faithfulness 基準、CP-20 回歸測試結果，**全部是在「錯誤索引」上跑出的數字** |

### 影響範圍（已確認）
1. **CP-11 (Hybrid Search 索引建立)**：索引了錯誤專案
2. **CP-12~15 (RRF + 符號映射)**：優化的是錯誤專案的檢索效能
3. **CP-16~20 (生成整合 + 回歸測試)**：8 題測試題全針對 build_pyd/，驗收結果不代表 aaeonFramework 表現
4. **CP-21~25 (信心評估 + Faithfulness + Low 門檻)**：所有基準數據（72.2% 準確率、Faithfulness 0.45、provisional 門檻）皆在錯誤索引上校準
5. **CP-26 (NIM Logger)**：記錄的 API 呼叫日誌與實際目標專案無關

### 解決方案
1. **備份現有索引**（已完成）：`chroma_db.backup_build_pyd_20260717_154908/`, `bm25_index.pkl.backup_build_pyd_20260717_154908`
2. **確認 .env 正確設定**：GITLAB_URL=https://sts.aaeon.com.tw:11180/, GITLAB_PROJECT=153
3. **重建索引流程**：
   - `python gitlab_client.py` — 驗證連線
   - `python fetch_and_save.py` — 抓取 aaeonFramework 原始碼
   - `python chunking.py` — 切分
   - `python embed_and_store.py` — Embedding 寫入 Chroma
   - `python keyword_index.py` — 建立 BM25 + 符號索引
4. **CP-30-C 130 題全量重跑**（已跑的 26 題 0% 命中為無效數據，不保留）

### 驗證標準
- Chroma collection count 應與 aaeonFramework 程式碼檔案切分後的 chunk 數一致
- BM25 corpus 內容應包含 .c, .h, .inf 檔案片段
- CP-30-C 「明確技術修復」類 9 題、「純功能支援」類 121 題 Top-3 命中率應顯著 > 0%

### 結論（已確認，非研判）
**CP-21~26 所有驗收結論（含 72.2% 準確率、Faithfulness 0.45、provisional low 門檻）均無效，因為它們測的是「RAG 對 build_pyd/ 的表現」，而非「RAG 對 aaeonFramework (Project 153) 的表現」。** 此問題屬於「已確認」（有原始索引內容直接證實），不屬「研判」。

**關鍵補充：CP-25 provisional 門檻在 aaeonFramework 語料上從未被驗證過。** 這是一個事實記錄，而非單純宣稱「已無效」。CP-25 的 18 題構造題與 CP-30 的 130 題真實歷史題，分屬不同專案（build_pyd vs aaeonFramework）、不同指標（Confidence 校準準確率 vs 檢索命中率），兩者不可直接比較。

---

## ⚠️ CP-30-C 驗證結果分類報告

### 明確技術修復類 (9 題)
- **命中率：100% (9/9)**
- Confidence 分布：high 3、medium 4、low 2
- 代表 Issue：#22941 (EC I2c write block bug)、#21713 (Raptor Lake I2C)、#17657 (Smbios OEM-STRING)、#39480 (BSOD fix) 等
- **結論**：Bug fix、BSOD、I2C/SMBUS 等真實技術問題，系統完全能檢索到正確檔案

### 純功能支援類 (121 題)
- **命中率：88.4% (107/121)**
- Confidence 分布：high 31、medium 71、low 11、error 8
- 代表 Issue：#40658 (MIX-ALND1-2G)、#40942 (PICO-PTH4) 等新增板卡支援
- **佔樣本比 93% (121/130)**，符合 CP-30-B 排除標準精神：
  - CP-30-A 盤點出 130 組有效配對，其中 121 組屬「純功能支援」（新增板卡、INF 設定）
  - CP-30-B **未額外排除**任何題目，全部 130 組納入測試集
  - 這反映專案實際開發模式：以新增板卡/功能為主，Bug fix 相對較少
- **非技術修復類的高命中率不應作為調低門檻依據**：
  - 板卡支援類查詢多為「新增 INF 設定」，GT 多為單一 `.inf` 檔案，語意匹配容易
  - 若要調低 Low 門檻，應基於 **9 題明確技術修復類**（或補充更多同類型真實技術問題）重新校準
  - 不能用「121 題板卡支援題的高命中率」當作調低門檻的依據

### 8 個 Error 歸類（已從命中率分母剔除）
| 類型 | 數量 | 代表 Issue | 根因 |
|------|------|------------|------|
| Chroma tenant 連線失敗 | 4 | #40357, #40844, #25931, #26133 | 併發 4 workers 衝擊 Chroma，暫時性連線中斷 |
| RustBindingsAPI 缺屬性 | 2 | #40942, #26158 | Chroma 版本兼容性問題，間歇性 |
| chroma_db 連線異常 | 2 | #40658, #26560 | 同上 |

**已記入 ISSUES_LOG.md 供後續追蹤。**

---

## ✅ 已解決問題

### 問題 1：BM25 中文查詢無法匹配英文程式碼
**解決狀態：✅ 已解決 (CP-9)**

### 現象
- 使用 `rank_bm25` 預設 tokenizer（按空白/標點切分）
- 中文查詢「推論引擎 裝置設定」tokenize 為 `["推論引擎", "裝置設定"]`
- 程式碼 corpus 全為英文（如 `infer`, `base`, `core`, `device`, `available`）
- **結果**：BM25 分數全為 0，完全失效

### 根因分析
| 層面 | 說明 |
|------|------|
| 語言不匹配 | 查詢為中文、文檔為英文，詞彙完全不重疊 |
| Tokenizer 缺陷 | 預設 `\w+` 無法處理中文，且不做字元級 n-gram |
| IDF 計算異常 | 查詢 token 不在 corpus 中 → IDF=0 → 分數=0 |

### 解決方案：字符級 n-gram + 查詢擴展

**修改檔案**：`hybrid_search.py`

```python
# 1. 字符級 n-gram tokenizer（適用中英混雜）
def ngram_tokenize(text: str, n: int = 3) -> List[str]:
    text = re.sub(r'\s+', '', text.lower())
    return [text[i:i+n] for i in range(len(text) - n + 1)]

# 2. 查詢擴展：中文關鍵字 → 對應英文技術詞
QUERY_EXPANSION = {
    "推論": ["infer", "inference", "model", "predict"],
    "引擎": ["engine", "core", "runtime"],
    "裝置": ["device", "gpu", "cpu", "auto"],
    "設定": ["config", "setting", "parameter"],
    "建立": ["build", "create", "make", "package"],
    "安裝包": ["wheel", "whl", "package", "dist"],
    "打包": ["build", "package", "setup", "cython"],
    "腳本": ["script", "python", "py"],
    "二進位": ["binary", "pyd", "dll", "compiled"],
    "危險": ["hazard", "danger", "risk", "zone"],
    "區域": ["region", "area", "polygon", "zone"],
    "偵測": ["detect", "detector", "detection", "analysis"],
    "GPIO": ["gpio", "dio", "pin", "digital"],
    "控制": ["control", "set", "status", "level"],
```

### 驗證結果
| 指標 | 修正前 | 修正後 |
|------|--------|--------|
| 中文查詢 BM25 分數 | 全 0 | 非 0，可融合 |
| RRF 融合後 Top-5 相關性 | 靠向量單靠 | 向量+BM25 互補 |

---

### 問題 2：查詢擴展硬編碼字典維護成本高
**解決狀態：✅ 已解決 (CP-12)**

### 現象
- `QUERY_EXPANSION` 字典需人工維護，換 repo 即失效
- 只覆蓋已知測試題詞彙，泛化能力差

### 解決方案：符號自動映射
**修改檔案**：`symbol_expansion.py`, `hybrid_search.py`

```python
# 從程式碼符號自動抽取 token（駝峰/底線拆分）
def extract_symbol_tokens(symbols: List[str]) -> Set[str]:
    tokens = set()
    for sym in symbols:
        # 駝峰式拆分
        tokens.update(re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)', sym))
        # 底線拆分
        tokens.update(sym.split('_'))
    return {t.lower() for t in tokens if len(t) >= 2}

# 查詢中英文詞與 symbol_tokens 交集 → +0.2 bonus
```

### 驗證結果
- 移除 `QUERY_EXPANSION` 硬編碼字典
- 5 題回歸測試：3 題改善、2 題持平、**0 題退步**

---

### 問題 3：加權融合分數尺度不一
**解決狀態：✅ 已解決 (CP-13)**

### 現象
- 向量分數範圍 [0,1]、BM25 分數範圍 [0, 10+]、符號 bonus 固定 0.2
- 直接加權融合導致 BM25 主導、向量幾乎無影響

### 解決方案：RRF (Reciprocal Rank Fusion)
**修改檔案**：`hybrid_search.py`

```python
def _reciprocal_rank_fusion(ranked_lists: List[List[str]], k: int = 60) -> Dict[str, float]:
    scores = {}
    for ranked in ranked_lists:
        for rank, chunk_id in enumerate(ranked, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return scores
```

### 驗證結果
| 指標 | 加權融合 | RRF |
|------|----------|-----|
| 向量貢獻度 | ~5% | ~33% (三路均等) |
| 中文查詢 Top-1 準確率 | 40% | 60% |

---

### 問題 4：POST 端點中文 body 解析失敗
**解決狀態：✅ 已記錄為已知限制 (CP-21)**

### 現象
- Windows/MSYS 下 `curl -X POST` 直接帶中文 body 會亂碼（codepage 950/Big5 轉碼問題）
- GET 端點正常（URL encode 後傳遞）

### 解決方案
- **GET 端點**：中文查詢用 URL encode（已驗證正常）
- **POST 端點**：用 `printf > file` + `curl --data-binary @file` 方式繞過 codepage 問題
- **文檔化**：MANUAL.md、AGENTS.md 已記錄「POST 中文 body 必須用檔案方式」

---

### 問題 5：Chroma 併發連線失敗
**解決狀態：✅ 已解決 (CP-31)**

### 現象
- 130 題測試中 4 個 Chroma tenant 連線失敗、2 個 RustBindingsAPI 缺屬性、2 個 chroma_db 連線異常
- 根因：4 workers 併發衝擊 Chroma PersistentClient，非線程安全

### 解決方案
**修改檔案**：`hybrid_search.py`

```python
# 全域 ChromaDB 連線池（線程安全單例）
_chroma_client = None
_chroma_collection = None
_chroma_lock = threading.Lock()

def _get_chroma_collection():
    global _chroma_client, _chroma_collection
    with _chroma_lock:
        if _chroma_collection is None:
            _chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
            _chroma_collection = _chroma_client.get_collection(COLLECTION_NAME)
        return _chroma_collection

# 指數退避重試
def _chroma_query_with_retry(collection, query_embeddings, n_results, include):
    last_error = None
    for attempt in range(CHROMA_MAX_RETRIES + 1):
        try:
            return collection.query(...)
        except Exception as e:
            last_error = e
            if attempt < CHROMA_MAX_RETRIES:
                wait_time = CHROMA_RETRY_BASE_DELAY * (2 ** attempt)
                time.sleep(wait_time)
    raise RuntimeError(...)
```

### 驗證結果
- CP-31 期間 130 題重跑：**0 個 Chroma 連線錯誤**
- 單 worker 序列跑：穩定無錯誤

---

### 問題 6：NIM API 429/503 重試邏輯不完整
**解決狀態：✅ 已解決 (CP-31, CP-32-A, CP-33)**

### 現象
- 僅 429 有重試，503、timeout 無重試直接拋出
- 重試間隔固定，未讀取 `Retry-After` header
- fallback 觸發路徑從未被驗證（CP-32-A 修復）

### 解決方案（跨 CP-31/32/33 累積修復）
**修改檔案**：`hybrid_search.py`、`generate_coding_suggestion.py`、`nim_logger.py`、`rate_limiter.py`

1. **統一重試邏輯**：429、503、timeout 皆重試，讀取 `Retry-After`，否則指數退避
2. **全局限流器**：`rate_limiter.py` 35 RPM 保守值（NVIDIA 免費層 40 RPM 帳號級共用配額）
3. **Header 記錄**：`log_nim_call` 新增 `response_headers`，過濾記錄 `rate`/`retry`/`limit`/`reset` 相關
4. **最小等待保護**：`Retry-After` 為空/0/非數字時，最小等待 10s
5. **動態調整規則程式碼化**：24h 0 次 429 → 調高 20%（上限 38 RPM）；出現 429 → 立即打八折，記錄到 ISSUES_LOG.md

### 驗證結果
- **CP-32-A**：fallback 觸發路徑驗證通過，SQLite + JSONL 皆記錄 `status_code`/`error`/`fallback_triggered`
- **CP-33**：抽樣 20 題，**429 次數：0**（修復前頻繁觸發），主要錯誤為 503（上游不穩），非限流導致

---

### 問題 7：CP-30-C 歷史回報品質事故
**解決狀態：✅ 已記錄制度修正 (CP-30 期間發現，CP-31 制度化)**

### 現象
- CP-30-C 期間對 #26560、#26158 兩題回報為「check_file_hit 去重 bug 導致未命中」
- 實際經要求貼原始 JSON 核對後發現：兩題皆為真實檢索失敗（Top-3 均未含 GT），check_file_hit 邏輯經 130 題全量核對無 bug
- **此為專案歷史首次發現回報內容被完全編造**

### 制度修正（已寫入 AGENTS.md）
1. **貼原始輸出，不要摘要** — 所有結論性描述必須附可核對的原始資料
2. **用詞對應證據強度** — 已確認 / 研判 / 原因未明，不可混用
3. **宣稱「已寫入檔案」時，附上寫入後重新讀取的內容**
4. **規格要求 GET 和 POST 都測，就是兩個都要過**
5. **外部 API 遇到 429/503，不可只靠「重試 N 次」硬闖** — 讀取 `Retry-After`、指數退避、記錄 fallback

---

## 📝 新增問題時請遵循以下格式

### 問題 X：[標題]
**解決狀態：✅ 已解決 / 🔄 進行中 / ❌ 未解決 / 📝 已記錄為已知限制**

### 現象
- 具體觀察到的症狀、錯誤訊息、失敗案例

### 根因分析
| 層面 | 說明 |
|------|------|
| ... | ... |

### 解決方案
**修改檔案**：`xxx.py`

```python
# 關鍵程式碼片段
```

### 驗證結果
| 指標 | 修正前 | 修正後 |
|------|--------|--------|
| ... | ... | ... |

### 結論（已確認 / 研判 / 原因未明）
標註證據強度，不可混用。