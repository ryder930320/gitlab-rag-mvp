"""GitLab RAG 查詢介面 - 供 Hermes Agent 呼叫"""
import os
import httpx
import chromadb
from dotenv import load_dotenv

load_dotenv()

NIM_API_KEY = os.getenv("NIM_API_KEY")
NIM_EMBED_MODEL = os.getenv("NIM_EMBED_MODEL")
NIM_EMBED_URL = "https://integrate.api.nvidia.com/v1/embeddings"

CHROMA_DIR = "chroma_db"
COLLECTION_NAME = "gitlab_rag"

_client = None
_collection = None


def _get_collection():
    """Lazy 初始化 Chroma collection"""
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(path=CHROMA_DIR)
        _collection = _client.get_collection(COLLECTION_NAME)
    return _collection


def _embed_query(text: str) -> list[float]:
    """將查詢文字轉為向量"""
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


def _vector_search(question: str, top_k: int) -> list[dict]:
    """純向量檢索（CP-7 原始邏輯）"""
    query_embedding = _embed_query(question)
    collection = _get_collection()
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"]
    )
    hits = []
    for i in range(len(results["ids"][0])):
        meta = results["metadatas"][0][i]
        hits.append({
            "content": results["documents"][0][i],
            "file_path": meta.get("file_path", ""),
            "source_type": meta.get("source_type", ""),
            "language": meta.get("language", ""),
            "chunk_index": meta.get("chunk_index", 0),
            "created_at": meta.get("created_at", ""),
            "score": 1.0 - results["distances"][0][i]
        })
    return hits


def query_gitlab_context(question: str, top_k: int = 5, use_hybrid: bool = True) -> list[dict]:
    """
    查詢 GitLab 專案上下文

    Args:
        question: 使用者問題
        top_k: 回傳前 k 筆結果
        use_hybrid: True=混合檢索(向量+BM25+符號), False=純向量檢索(CP-7 邏輯)

    Returns:
        list[dict]: [
            {
                "content": str,
                "file_path": str,
                "source_type": str,
                "language": str,
                "chunk_index": int,
                "created_at": str,
                "score": float,
                "rrf_score": float,
                "score_vector": float,
                "score_bm25": float,
                "vec_rank": int,
                "bm25_rank": int,
                "symbol_hits": int,
            },
            ...
        ]
    """
    if not NIM_API_KEY or not NIM_EMBED_MODEL:
        raise RuntimeError("請先設定 .env 中的 NIM_API_KEY 和 NIM_EMBED_MODEL")

    if use_hybrid:
        # 混合檢索：呼叫 hybrid_search.py
        from hybrid_search import hybrid_search
        raw_results = hybrid_search(question, top_k=top_k)
        # 統一輸出格式（保留原始規定欄位 + hybrid 額外欄位供 confidence_evaluator 使用）
        hits = []
        for r in raw_results:
            hits.append({
                "content": r["content"],
                "file_path": r["file_path"],
                "source_type": r["source_type"],
                "language": r.get("language", ""),
                "chunk_index": r.get("chunk_index", 0),
                "created_at": r.get("created_at", ""),
                "score": r["score"],  # 這是 rrf_score
                "rrf_score": r.get("rrf_score", 0.0),
                "score_vector": r.get("score_vector", 0.0),
                "score_bm25": r.get("score_bm25", 0.0),
                "vec_rank": r.get("vec_rank", 999),
                "bm25_rank": r.get("bm25_rank", 999),
                "symbol_hits": r.get("symbol_hits", 0),
            })
        return hits
    else:
        # 純向量檢索：CP-7 原始邏輯
        return _vector_search(question, top_k)


# 便利函式：格式化輸出供人類閱讀
def format_results(results: list[dict]) -> str:
    """將查詢結果格式化為可讀字串"""
    if not results:
        return "無相關結果"
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"[{i}] score={r['score']:.4f} | {r['source_type']} | {r['file_path']} | chunk#{r['chunk_index']}")
        lines.append(f"    {r['content'][:200]}...")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    # 簡單測試：兩種模式對照
    test_q = "這個專案怎麼處理 GPIO 控制？"
    print(f"測試查詢：{test_q}\n")

    print("=== use_hybrid=True (混合檢索) ===")
    res_hybrid = query_gitlab_context(test_q, top_k=3, use_hybrid=True)
    print(format_results(res_hybrid))

    print("\n=== use_hybrid=False (純向量) ===")
    res_vector = query_gitlab_context(test_q, top_k=3, use_hybrid=False)
    print(format_results(res_vector))


def get_coding_suggestion(question: str, top_k: int = 5) -> dict:
    """
    完整流程：檢索 → 信心評估 → Prompt 建構 → 生成 → 組裝回傳
    供 Hermes Agent 直接呼叫，取得帶信心等級與來源的程式碼建議

    Args:
        question: 使用者問題
        top_k: 檢索前 k 筆

    Returns:
        {
            "suggestion": str,
            "confidence": "high" | "medium" | "low",
            "confidence_reason": str,
            "sources": list[dict],  # {"file_path": str, "chunk_index": int, "preview": str}
        }
    """
    from generate_coding_suggestion import generate_coding_suggestion
    return generate_coding_suggestion(question, top_k=top_k)
