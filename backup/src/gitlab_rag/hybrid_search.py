"""混合檢索融合邏輯 (CP-13 RRF 版本 + CP-23 Query Expansion + CP-24 Reranker)
- 取代原本的 weighted score fusion
- 改用 Reciprocal Rank Fusion (RRF)：只比較排名、不比較分數
- 符號匹配 (CP-12) 作為第三條排序清單餵入 RRF
- 查詢擴展 (CP-23)：純中文查詢經 LLM 擴展英文技術詞彙，僅餵給 BM25/符號路徑
- Reranker (CP-24)：RRF 融合後使用 NIM 生成模型重排序
"""
import json
import pickle
import re
import time
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
# 使用相對於專案根目錄的絕對路徑
BASE_DIR = Path(__file__).resolve().parents[2]
BM25_INDEX_PATH = str(BASE_DIR / "data" / "bm25_index.pkl")

# RRF 參數
RRF_K = 60  # 業界慣用預設值

# Reranker 開關（可用環境變數關閉）
RERANKER_ENABLED = os.getenv("RERANKER_ENABLED", "true").lower() == "true"

# 匯入 logger
from .nim_logger import log_nim_call


def _embed_query(text: str, question: str = "") -> List[float]:
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
    start = time.time()
    fallback = False
    error_msg = None
    response_json = None
    status_code = 200
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(NIM_EMBED_URL, headers=headers, json=payload)
            latency_ms = int((time.time() - start) * 1000)
            status_code = resp.status_code
            resp.raise_for_status()
            response_json = resp.json()
            return response_json["data"][0]["embedding"]
    except Exception as e:
        latency_ms = int((time.time() - start) * 1000)
        error_msg = str(e)
        status_code = getattr(e, 'response', None)
        status_code = status_code.status_code if status_code else 0
        fallback = False
        raise
    finally:
        log_nim_call(
            query=question or text,
            model=NIM_EMBED_MODEL,
            call_type="embedding",
            request_payload=payload,
            response_payload=response_json,
            finish_reason=None,
            fallback_triggered=fallback,
            error=error_msg,
            latency_ms=latency_ms,
            status_code=status_code,
        )


def _load_bm25_index() -> Dict[str, Any]:
    """載入 BM25 索引與 chunks"""
    with open(BM25_INDEX_PATH, "rb") as f:
        return pickle.load(f)


def _char_ngrams(text: str, n: int = 3) -> List[str]:
    """字符級 n-gram tokenizer（適用於跨語言匹配）"""
    text = text.lower()
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
        df = {}
        for doc in self.corpus:
            for word in set(doc):
                df[word] = df.get(word, 0) + 1
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
    corpus = []
    for chunk in chunks:
        content = chunk["content"]
        meta = chunk["metadata"]
        symbols = " ".join(meta.get("symbols", []))
        file_path = meta.get("file_path", "")
        fname = Path(file_path).stem if file_path else ""
        full_text = f"{content} {symbols} {fname}"
        tokens = _char_ngrams(full_text, n=3)
        corpus.append(tokens)

    return CharNGramBM25(corpus)


def _reciprocal_rank_fusion(ranked_lists: List[List[str]], k: int = RRF_K) -> Dict[str, float]:
    """
    Reciprocal Rank Fusion
    
    Args:
        ranked_lists: 多個已排序的 chunk_id 清單（每個清單按相關性由高到低）
        k: RRF 常數，預設 60
    
    Returns:
        {chunk_id: rrf_score}
    """
    scores = {}
    for ranked in ranked_lists:
        for rank, chunk_id in enumerate(ranked, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return scores


def _get_symbol_ranked_list(question: str, chunks: List[Dict]) -> List[str]:
    """
    根據符號匹配產生排序清單
    命中 symbol_token 的 chunk 被視為相關，按 symbol_token 數量排序
    """
    from .symbol_expansion import extract_symbol_tokens, symbol_token_bonus
    
    # 計算每個 chunk 的符號匹配分數
    chunk_scores = []
    for chunk in chunks:
        meta = chunk["metadata"]
        if meta.get("source_type") != "code":
            continue
        symbols = meta.get("symbols", [])
        if not symbols:
            continue
        stokens = extract_symbol_tokens(symbols)
        bonus = symbol_token_bonus(question, set(stokens))
        if bonus > 0:
            # 用命中的 token 數量作為排序依據
            hit_count = len(set(re.findall(r'[a-zA-Z]{2,}', question.lower())) & set(stokens))
            chunk_scores.append((hit_count, meta.get("global_chunk_id", 0)))
    
    # 按 hit_count 降序排序
    chunk_scores.sort(key=lambda x: x[0], reverse=True)
    return [str(cid) for _, cid in chunk_scores]


def hybrid_search(
    question: str,
    top_k: int = 5
) -> List[Dict[str, Any]]:
    """
    混合檢索：向量 + 字符級 BM25 + 符號匹配 → RRF 融合
    
    Args:
        question: 查詢字串
        top_k: 回傳前 k 筆
    
    Returns:
        list[dict]: 含 content, file_path, source_type, score, score_vector, score_bm25, rrf_score, symbol_hits, ...
    """
    # 1. 載入資料
    index_data = _load_bm25_index()
    chunks = index_data["chunks"]

    # 建立字符級 BM25
    bm25 = _build_char_ngram_bm25(chunks)

    # 2. 查詢擴展 (CP-23)：純中文查詢擴展英文技術詞彙，僅用於 BM25/符號路徑
    from .query_expander import expand_chinese_query
    expansion_result = expand_chinese_query(question)
    bm25_query = expansion_result["expanded_query_for_bm25"]
    expanded_terms = expansion_result["expanded_terms"]
    
    # 向量檢索使用原始問題
    query_embedding = _embed_query(question)
    # BM25/符號路徑使用擴展後的查詢
    query_tokens = _char_ngrams(bm25_query, n=3)
    candidate_k = top_k * 3

    # 3. 向量檢索
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    collection = client.get_collection(COLLECTION_NAME)

    vec_results = collection.query(
        query_embeddings=[query_embedding],
        n_results=candidate_k,
        include=["documents", "metadatas", "distances"]
    )

    vec_ranked = []
    vec_candidates = {}
    for i in range(len(vec_results["ids"][0])):
        meta = vec_results["metadatas"][0][i]
        cid = str(vec_results["ids"][0][i])
        vec_ranked.append(cid)
        vec_candidates[cid] = {
            "chunk_id": cid,
            "content": vec_results["documents"][0][i],
            "file_path": meta.get("file_path", ""),
            "source_type": meta.get("source_type", ""),
            "language": meta.get("language", ""),
            "chunk_index": meta.get("chunk_index", 0),
            "created_at": meta.get("created_at", ""),
            "score_vector": 1.0 - vec_results["distances"][0][i],
            "symbols": meta.get("symbols", []),
            "vec_rank": i + 1
        }

    # 4. BM25 檢索（使用擴展後的查詢）
    bm25_scores = bm25.get_scores(query_tokens)
    bm25_top_indices = sorted(range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True)[:candidate_k]

    bm25_ranked = []
    bm25_candidates = {}
    for rank, idx in enumerate(bm25_top_indices, start=1):
        chunk = chunks[idx]
        meta = chunk["metadata"]
        cid = str(meta.get("global_chunk_id", idx))
        bm25_ranked.append(cid)
        bm25_candidates[cid] = {
            "chunk_id": cid,
            "content": chunk["content"],
            "file_path": meta.get("file_path", ""),
            "source_type": meta.get("source_type", ""),
            "language": meta.get("language", ""),
            "chunk_index": meta.get("chunk_index", 0),
            "created_at": meta.get("created_at", ""),
            "score_bm25": bm25_scores[idx],
            "symbols": meta.get("symbols", []),
            "bm25_rank": rank
        }

    # 5. 符號匹配排序清單（使用擴展後的查詢）
    symbol_ranked = _get_symbol_ranked_list(bm25_query, chunks)

    # 6. RRF 融合
    ranked_lists = [vec_ranked, bm25_ranked, symbol_ranked]
    rrf_scores = _reciprocal_rank_fusion(ranked_lists, RRF_K)

    # 7. 合併所有候選並按 RRF 分數排序
    all_candidates = {}
    for cid, cand in vec_candidates.items():
        all_candidates[cid] = cand
    for cid, cand in bm25_candidates.items():
        if cid in all_candidates:
            # 合併資訊
            all_candidates[cid]["score_bm25"] = cand["score_bm25"]
            all_candidates[cid]["bm25_rank"] = cand["bm25_rank"]
        else:
            all_candidates[cid] = cand

    # 加上 RRF 分數和排序資訊
    for cid, cand in all_candidates.items():
        cand["rrf_score"] = rrf_scores.get(cid, 0.0)
        cand["vec_rank"] = cand.get("vec_rank", 999)
        cand["bm25_rank"] = cand.get("bm25_rank", 999)
        # 符號命中數（使用擴展後查詢計算）
        symbols = cand.get("symbols", [])
        if symbols:
            from .symbol_expansion import extract_symbol_tokens, symbol_token_bonus
            stokens = extract_symbol_tokens(symbols)
            cand["symbol_hits"] = len(set(re.findall(r'[a-zA-Z]{2,}', bm25_query.lower())) & set(stokens))
        else:
            cand["symbol_hits"] = 0

    # 8. 排序並回傳 top_k
    sorted_candidates = sorted(all_candidates.values(), key=lambda x: x["rrf_score"], reverse=True)
    results = sorted_candidates[:top_k]

    # 9. Reranker 重排序 (CP-24)：在 hybrid_search 之後、confidence_evaluator 之前
    if RERANKER_ENABLED:
        from .reranker import rerank_results
        results = rerank_results(question, results, top_k=top_k, enabled=RERANKER_ENABLED)

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
            "score": r.get("rerank_score", r["rrf_score"]),  # 優先使用 rerank_score，否則回退到 rrf_score
            "score_vector": r.get("score_vector", 0.0),
            "score_bm25": r.get("score_bm25", 0.0),
            "rrf_score": r["rrf_score"],
            "rerank_score": r.get("rerank_score"),
            "rerank_rank": r.get("rerank_rank"),
            "vec_rank": r.get("vec_rank", 999),
            "bm25_rank": r.get("bm25_rank", 999),
            "symbol_hits": r.get("symbol_hits", 0),
            "expanded_terms": expanded_terms,  # 記錄擴展詞彙供除錯
        })

    return output


if __name__ == "__main__":
    test_questions = [
        "專案使用什麼推論引擎？怎麼設定裝置？",
        "如何建立 whl 安裝包？",
    ]

    for q in test_questions:
        print(f"\n{'='*60}")
        print(f"查詢: {q}")
        print(f"{'='*60}")
        results = hybrid_search(q, top_k=5)
        for i, r in enumerate(results, 1):
            print(f"\n  Top-{i}: rrf={r['rrf_score']:.4f} | vec={r['score_vector']:.4f}(rank={r['vec_rank']}) | bm25={r['score_bm25']:.4f}(rank={r['bm25_rank']}) | symbol_hits={r['symbol_hits']}")
            print(f"         file={r['file_path']} | type={r['source_type']} | chunk#{r['chunk_index']}")
            preview = r['content'][:120].replace('\n', ' ')
            print(f"         content: {preview}...")