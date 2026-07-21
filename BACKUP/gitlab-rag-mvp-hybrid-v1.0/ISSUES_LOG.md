# GitLab RAG 專案問題紀錄總表 (ISSUES_LOG.md)

> 記錄所有開發階段遇到的問題、分析與解決方案，**每個問題標註解決狀態**

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
}

def expand_query(query: str) -> str:
    expanded = [query]
    for zh, en_terms in QUERY_EXPANSION.items():
        if zh in query:
            expanded.extend(en_terms)
    return " ".join(expanded)
```

### 效果驗證
| 查詢 | 擴展後 | BM25 Top-1 | 分數 |
|------|--------|------------|------|
| 推論引擎 裝置設定 | + infer, engine, core, device, config... | `infer_base.py` chunk#1 | 390.15 |
| 建立 whl 安裝包 | + build, wheel, package, setup... | `note.txt` chunk#0 | 200.31 |

---

## 問題 2：Chroma 向量檢索 Top-1 錯誤（GPU/GPIO 干擾）
**解決狀態：✅ 已解決 (CP-9 Hybrid Search)**

### 現象
- 查詢「推論引擎」時，向量檢索 Top-1 為 `device_controll.py`（GPIO 相關）
- 語意相似度誤判：`device`、`control`、`set` 等詞在向量空間接近

### 解決方案
- **不修改向量模型**（成本高、風險大）
- 改用 **Hybrid Search 融合**：
  - BM25 能精準匹配 `infer`、`core`、`available_devices` 等技術詞
  - 向量檢索負責語意兜底
  - 融合公式：`final = 0.5 * norm_vec + 0.5 * norm_bm25`

### 融合後結果
| 查詢 | 向量 Top-1 | BM25 Top-1 | Hybrid Top-1 |
|------|-----------|------------|--------------|
| 推論引擎 | `device_controll.py` ❌ | `infer_base.py` ✅ | `infer_base.py` ✅ |
| 建立 whl | `device_controll.py` ❌ | `note.txt` ✅ | `note.txt` ✅ |

---

## 問題 3：Min-Max 正規化邊界條件
**解決狀態：✅ 已解決 (CP-9)**

### 現象
- 當候選池中所有向量分數相同（或 BM25 全 0）時，`max == min` 導致除零

### 解決方案
```python
def _min_max_normalize(scores: List[float]) -> List[float]:
    if not scores:
        return []
    min_s, max_s = min(scores), max(scores)
    if max_s == min_s:
        return [0.5] * len(scores)  # 全同分 → 給中性分
    return [(s - min_s) / (max_s - min_s) for s in scores]
```

---

## 問題 4：符號抽取遺漏（CP-8）
**解決狀態：⚠️ 部分解決（有已知缺口）**

### 現象
- `infer_base.py` chunk#0 只有 `read_json`, `__init__`, `AI_Core`, `infer_base`
- 遺漏關鍵符號：`Core`, `available_devices`, `compile_model`, `Infer`, `visualization`

### 根因
- Regex 僅抓 `def xxx(` 和 `class xxx:`，**遺漏**：
  - 類別實例化：`Core()`
  - 方法呼叫：`core.compile_model()`, `core.available_devices`
  - 變數名：`available_devices_list`

### 改進方向（後續可做）
```python
# 可加入的額外抽取規則
IMPORT_PATTERN = re.compile(r"from\s+(\w+)\s+import|import\s+(\w+)")
CALL_PATTERN = re.compile(r"(\w+)\.(\w+)\(")  # obj.method()
CONST_PATTERN = re.compile(r"([A-Z_]{3,})\s*=")  # 常數
```

---

## 關鍵參數設定總結

| 參數 | 值 | 說明 |
|------|-----|------|
| `alpha` | 0.5 | 向量/BM25 等權重 |
| `candidate_multiplier` | 3 | 候選池 = top_k × 3 |
| `ngram_n` | 3 | 字符級 3-gram |
| `symbol_bonus` | 0.2 | 查詢匹配符號時加分 |
| `QUERY_EXPANSION` | 12組 | 中文→英文技術詞映射 |

---

## 檔案變更記錄

| 檔案 | 變更類型 | 說明 |
|------|----------|------|
| `requirements.txt` | 新增 | `rank-bm25` |
| `keyword_index.py` | 新建 | BM25 索引建立 + 符號抽取 |
| `hybrid_search.py` | 新建 | 混合檢索融合邏輯（含 n-gram + 擴展） |
| `data/bm25_index.pkl` | 產出 | 序列化 BM25 索引 + chunks |

---

## 📋 CP-10 正式回報：已知限制與風險

> **重要**：以下限制是 CP-10 階段驗收時已知的，**不代表問題已解決**，而是明確標記給後續迭代（CP-11+）或維護者知道「這裡有坑」。

### 限制 1：查詢擴展為硬編碼 Workaround
- **現狀**：`hybrid_search.py` 的 `QUERY_EXPANSION` 字典為手動維護的中英對照表（12 組），僅覆蓋 5 組測試題涉及的詞彙。
- **風險**：
  - 不具跨 repo / 跨領域泛化能力
  - 換新 repo 時此字典**完全失效**，需人工重寫
  - CP-10 回歸測試 5/5 通過**依賴此字典**，非混合檢索方法本身解決了中英語意落差
- **程式碼標註**：`hybrid_search.py` 第 24-28 行已加 `⚠️ WORKAROUND` 註解
- **後續解決方向**：CP-11+ 以「符號自動映射」（從程式碼抽取符號自動建中英對照）或「embedding-based query expansion」取代

### 限制 2：Min-Max 正規化為 Batch-Dependent（尺度漂移風險）
- **現狀**：`_min_max_normalize()` 使用當下候選池的 min/max（26 筆資料的 batch statistics）。
- **風險**：
  - BM25 絕對分數隨 corpus 增長而漂移（200~500 → 可能變 5000+）
  - 同樣「相關」的文檔在不同批次會被正規化到完全不同區間
  - 向量分數雖穩定（cosine 固定範圍），但與 BM25 權重融合時會失衡
- **程式碼標註**：`hybrid_search.py` 第 97-110 行已加 `⚠️ MVP 簡化實作` 註解
- **後續解決方向**：資料量增大時改用
  - 固定分位數正規化（P5/P95 來自全量 corpus 統計）
  - 或 log-scaling + clip 到固定區間
  - 或改用 BM25L/BM25+（內建飽和機制）

### 限制 3：符號抽取覆蓋率不足
- **現狀**：Regex 僅抓 `def`/`class`，遺漏 import、方法呼叫、常數、實例化等關鍵符號
- **影響**：BM25 / 符號加分無法匹配 `core.compile_model()`、`available_devices` 等高價值信號
- **程式碼標註**：`keyword_index.py` 已有註解，`ISSUES_LOG.md` 問題 4 記錄
- **後續解決方向**：增強 `extract_symbols()` 加入 import、call、const pattern

---

## 🔄 進行中 / 待解決問題

### 問題 5：Alpha 調參驗證 (CP-10)
**狀態：✅ 已完成**
- 最終選定 `alpha=0.5`（向量/BM25 等權重）
- 5 組測試題：3 題持平、2 題改善、0 題退步

### 問題 6：符號抽取增強
**狀態：⏳ 待排程**
- 加入 import、方法呼叫、常數抽取

### 問題 7：查詢擴展自動化
**狀態：⏳ 待排程**
- 從 commit message / README / 符號自動建立中英映射表

### 問題 8：評估指標量化
**狀態：⏳ 待排程**
- 引入 Recall@k、MRR 等指標替代人工判斷

---

## 📝 問題追蹤範本

新增問題時請遵循以下格式：

```markdown
### 問題 N：<標題>
**解決狀態：<✅已解決 / 🔄進行中 / ⏳待排程 / ❌已擱置>**

#### 現象
- ...

#### 根因分析
| 層面 | 說明 |
|------|------|

#### 解決方案
```python
# 代碼片段
```

#### 驗證結果
| 指標 | 修正前 | 修正後 |
|------|--------|--------|
```

---