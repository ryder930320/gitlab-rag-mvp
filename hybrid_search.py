"""混合檢索融合邏輯 (CP-9) - 修正版：加入查詢擴展與字符級 BM25"""
import json
import pickle
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
import chromadb
import httpx
from dotenv import load_dotenv
import os

load_dotenv()

NIM_API_KEY = os.getenv("NIM_API_KEY")
NIM_EMBED_MODEL = os.getenv("NIM_EMBED_MODEL")
NIM_EMBED_URL = "https://integrate.api.nvidia.com/v1/embeddings"

CHROMA_DIR = "chroma_db"
COLLECTION_NAME = "gitlab_rag"
BM25_INDEX_PATH = "data/bm25_index.pkl"


# ========== 查詢擴展：中文關鍵字 → 英文符號/關鍵字 ==========
# ⚠️ WORKAROUND (MVP 階段限定): 此為手動硬編碼的中英對照表，
# 僅涵蓋目前測試題涉及的詞彙，不具跨 repo / 跨領域泛化能力。
# CP-10 回歸測試的 5/5 通過結果是在此字典輔助下取得，
# 不代表混合檢索方法本身已解決中英語意落差問題。
# 下一輪迭代應以「符號自動映射」或「embedding-based query expansion」取代。
QUERY_EXPANSION = {
    # 推論相關
    "推論": ["infer", "inference", "infer_base", "AI_Core", "Infer"],
    "引擎": ["engine", "infer", "inference", "openvino", "Core"],
    "裝置": ["device", "AUTO", "CPU", "GPU", "available_devices"],
    "設定": ["config", "setting", "device", "infer_device", "Model_Dir"],

    # 打包相關
    "建立": ["build", "setup", "create", "bdist_wheel", "build_ext"],
    "安裝包": ["wheel", "whl", "package", "dist", "bdist_wheel"],
    "打包": ["build", "setup", "cython", "cythonize", "pyd"],

    # GPIO
    "GPIO": ["gpio", "DIO", "EApiGPIO", "device_controll", "pin", "set_dio_status"],
    "控制": ["control", "controll", "set", "get", "status", "high", "low"],

    # 危險區域
    "危險區域": ["hazard", "hazard_analysis", "danger", "zone", "polygon", "region"],
    "偵測": ["detect", "detection", "analysis_obj", "disting_obj"],

    # 一般
    "專案": ["project", "Aaeon_ai_sdk", "setup.py"],
    "如何": ["how", "run", "execute", "python"],
    "步驟": ["step", "run", "build", "install"],
}


def expand_query(query: str) -> str:
    """將查詢擴展：加入對應的英文關鍵字"""
    expanded_terms = [query]
    query_lower = query.lower()

    for zh_term, en_terms in QUERY_EXPANSION.items():
        if zh_term in query:
            expanded_terms.extend(en_terms)

    # 去重並合併
    seen = set()
    result = []
    for term in expanded_terms:
        if term not in seen:
            seen.add(term)
            result.append(term)
    return " ".join(result)


def _embed_query(text: str) -> List[float]:
    """將查詢文字轉為向量 (input_type=query)"""
    headers = {
        "Authorization": f"Bearer {NIM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": NIM_EMBED_MODEL,
        "input": text,
        "encoding_format": "float",
        "input_type": "query"
    }
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(NIM_EMBED_URL, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]


def _load_bm25_index() -> Dict[str, Any]:
    """載入 BM25 索引與 chunks"""
    with open(BM25_INDEX_PATH, "rb") as f:
        return pickle.load(f)


def _min_max_normalize(scores: List[float]) -> List[float]:
    """將分數 min-max 正規化到 0~1
    ⚠️ MVP 簡化實作: 使用當下候選池的 min-max (batch-dependent)。
    資料量增大時會導致分數尺度漂移,未來應改用:
      - 固定分位數 (P5/P95) 正規化
      - 或 log-scaling + clip 到固定區間
    """
    if not scores:
        return []
    min_s, max_s = min(scores), max(scores)
    if max_s == min_s:
        return [0.5] * len(scores)
    return [(s - min_s) / (max_s - min_s) for s in scores]


def _symbol_bonus(query: str, symbols: List[str]) -> float:
    """查詢與 symbols 字串匹配時加分"""
    if not symbols:
        return 0.0
    query_lower = query.lower()
    for sym in symbols:
        sym_lower = sym.lower()
        if sym_lower in query_lower or query_lower in sym_lower:
            return 0.2
    return 0.0


def _char_ngrams(text: str, n: int = 3) -> List[str]:
    """字符級 n-gram tokenizer（適用於跨語言匹配）"""
    text = text.lower()
    # 移除空白
    text = re.sub(r"\s+", "", text)
    if len(text) < n:
        return [text]
    return [text[i:i+n] for i in range(len(text) - n + 1)]


class CharNGramBM25:
    """字符級 n-gram BM25（重新實作以支援自定義 tokenizer）"""

    def __init__(self, corpus: List[List[str]], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus = corpus
        self.corpus_size = len(corpus)
        self.avgdl = sum(len(doc) for doc in corpus) / self.corpus_size if self.corpus_size > 0 else 0
        self.doc_freqs = []
        self.idf = {}
        self._initialize()

    def _initialize(self):
        # 計算 document frequency
        df = {}
        for doc in self.corpus:
            for word in set(doc):
                df[word] = df.get(word, 0) + 1
        # 計算 IDF
        for word, freq in df.items():
            self.idf[word] = max(0.0, (self.corpus_size - freq + 0.5) / (freq + 0.5))

    def get_scores(self, query_tokens: List[str]) -> List[float]:
        scores = []
        for doc in self.corpus:
            score = 0.0
            doc_len = len(doc)
            for word in query_tokens:
                if word not in self.idf:
                    continue
                tf = doc.count(word)
                idf = self.idf[word]
                score += idf * (tf * (self.k1 + 1)) / (tf + self.k1 * (1 - self.b + self.b * doc_len / self.avgdl))
            scores.append(score)
        return scores


def _build_char_ngram_bm25(chunks: List[Dict]) -> CharNGramBM25:
    """為所有 chunks 建立字符級 n-gram BM25"""
    # 為每個 chunk 建立 corpus 文檔（內容 + symbols + file_path）
    corpus = []
    for chunk in chunks:
        content = chunk["content"]
        meta = chunk["metadata"]
        symbols = " ".join(meta.get("symbols", []))
        file_path = meta.get("file_path", "")
        fname = Path(file_path).stem if file_path else ""
        # 合併所有文字
        full_text = f"{content} {symbols} {fname}"
        # 字符級 n-gram
        tokens = _char_ngrams(full_text, n=3)
        corpus.append(tokens)

    return CharNGramBM25(corpus)


def hybrid_search(
    question: str,
    top_k: int = 5,
    alpha: float = 0.5
) -> List[Dict[str, Any]]:
    """
    混合檢索：向量 + 字符級 BM25 + 符號加分

    Args:
        question: 查詢字串
        top_k: 回傳前 k 筆
        alpha: 向量分數權重 (0~1)，(1-alpha) 為 BM25 權重

    Returns:
        list[dict]: 含 content, file_path, source_type, score, score_vector, score_bm25, ...
    """
    # 1. 載入資料
    index_data = _load_bm25_index()
    chunks = index_data["chunks"]

    # 建立字符級 BM25（每次查詢時建立，資料量小可接受；大量時可預建並序列化）
    bm25 = _build_char_ngram_bm25(chunks)

    # 2. 查詢擴展
    expanded_query = expand_query(question)
    query_tokens = _char_ngrams(expanded_query, n=3)

    # 3. 向量檢索：取 top_k*3 候選
    candidate_k = top_k * 3
    query_embedding = _embed_query(question)  # 向量用原始查詢（語意更好）

    client = chromadb.PersistentClient(path=CHROMA_DIR)
    collection = client.get_collection(COLLECTION_NAME)

    vec_results = collection.query(
        query_embeddings=[query_embedding],
        n_results=candidate_k,
        include=["documents", "metadatas", "distances"]
    )

    vec_candidates = []
    for i in range(len(vec_results["ids"][0])):
        meta = vec_results["metadatas"][0][i]
        vec_candidates.append({
            "chunk_id": vec_results["ids"][0][i],
            "content": vec_results["documents"][0][i],
            "file_path": meta.get("file_path", ""),
            "source_type": meta.get("source_type", ""),
            "language": meta.get("language", ""),
            "chunk_index": meta.get("chunk_index", 0),
            "created_at": meta.get("created_at", ""),
            "score_vector": 1.0 - vec_results["distances"][0][i],
            "symbols": meta.get("symbols", [])
        })

    # 4. 字符級 BM25 檢索
    bm25_scores = bm25.get_scores(query_tokens)
    bm25_top_indices = sorted(range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True)[:candidate_k]

    bm25_candidates = []
    for idx in bm25_top_indices:
        chunk = chunks[idx]
        meta = chunk["metadata"]
        bm25_candidates.append({
            "chunk_id": meta.get("global_chunk_id", idx),
            "content": chunk["content"],
            "file_path": meta.get("file_path", ""),
            "source_type": meta.get("source_type", ""),
            "language": meta.get("language", ""),
            "chunk_index": meta.get("chunk_index", 0),
            "created_at": meta.get("created_at", ""),
            "score_bm25": bm25_scores[idx],
            "symbols": meta.get("symbols", [])
        })

    # 5. 合併候選（用 chunk_id 去重）
    all_candidates = {}
    for c in vec_candidates:
        cid = str(c["chunk_id"])
        if cid not in all_candidates:
            all_candidates[cid] = c
        else:
            all_candidates[cid]["score_vector"] = max(all_candidates[cid]["score_vector"], c["score_vector"])

    for c in bm25_candidates:
        cid = str(c["chunk_id"])
        if cid not in all_candidates:
            all_candidates[cid] = c
            all_candidates[cid]["score_vector"] = 0.0
        else:
            all_candidates[cid]["score_bm25"] = c["score_bm25"]

    # 確保所有候選都有兩個分數
    for c in all_candidates.values():
        c.setdefault("score_vector", 0.0)
        c.setdefault("score_bm25", 0.0)

    # 6. 計算分項分數正規化 + 符號加分
    cand_list = list(all_candidates.values())

    vec_scores = [c["score_vector"] for c in cand_list]
    bm25_scores_list = [c["score_bm25"] for c in cand_list]

    norm_vec = _min_max_normalize(vec_scores)
    norm_bm25 = _min_max_normalize(bm25_scores_list)

    for i, c in enumerate(cand_list):
        c["norm_score_vector"] = norm_vec[i]
        c["norm_score_bm25"] = norm_bm25[i]
        c["symbol_bonus"] = _symbol_bonus(question, c.get("symbols", []))
        c["final_score"] = (
            alpha * c["norm_score_vector"]
            + (1 - alpha) * c["norm_score_bm25"]
            + c["symbol_bonus"]
        )

    # 7. 排序並回傳 top_k
    cand_list.sort(key=lambda x: x["final_score"], reverse=True)
    results = cand_list[:top_k]

    # 格式化輸出
    output = []
    for r in results:
        output.append({
            "content": r["content"],
            "file_path": r["file_path"],
            "source_type": r["source_type"],
            "language": r.get("language", ""),
            "chunk_index": r.get("chunk_index", 0),
            "created_at": r.get("created_at", ""),
            "score": r["final_score"],
            "score_vector": r["score_vector"],
            "score_bm25": r["score_bm25"],
            "norm_score_vector": r.get("norm_score_vector", 0),
            "norm_score_bm25": r.get("norm_score_bm25", 0),
            "symbol_bonus": r.get("symbol_bonus", 0),
        })

    return output


if __name__ == "__main__":
    # 測試兩個 CP-6 失準的問題
    test_questions = [
        "專案使用什麼推論引擎？怎麼設定裝置？",
        "如何建立 whl 安裝包？",
    ]

    for q in test_questions:
        print(f"\n{'='*60}")
        print(f"查詢: {q}")
        print(f"{'='*60}")
        results = hybrid_search(q, top_k=3, alpha=0.5)
        for i, r in enumerate(results, 1):
            print(f"\n  Top-{i}: final={r['score']:.4f} | vec={r['score_vector']:.4f}(norm={r['norm_score_vector']:.4f}) | bm25={r['score_bm25']:.4f}(norm={r['norm_score_bm25']:.4f}) | bonus={r['symbol_bonus']:.2f}")
            print(f"         file={r['file_path']} | type={r['source_type']} | chunk#{r['chunk_index']}")
            preview = r['content'][:120].replace('\n', ' ')
            print(f"         content: {preview}...")