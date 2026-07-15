"""GitLab RAG 查詢介面 - 供 Hermes Agent 呼叫 (MVP 版本：純向量檢索)"""
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


def query_gitlab_context(question: str, top_k: int = 5) -> list[dict]:
    """
    查詢 GitLab 專案上下文 (純向量檢索，MVP 版本)

    Args:
        question: 使用者問題
        top_k: 回傳前 k 筆結果

    Returns:
        list[dict]: [
            {
                "content": str,
                "file_path": str,
                "source_type": str,
                "language": str,
                "chunk_index": int,
                "created_at": str,
                "score": float
            },
            ...
        ]
    """
    if not NIM_API_KEY or not NIM_EMBED_MODEL:
        raise RuntimeError("請先設定 .env 中的 NIM_API_KEY 和 NIM_EMBED_MODEL")

    # 1. Embed query
    query_embedding = _embed_query(question)

    # 2. 檢索 Chroma
    collection = _get_collection()
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"]
    )

    # 3. 整理輸出
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
    # 簡單測試
    test_q = "這個專案怎麼處理 GPIO 控制？"
    print(f"測試查詢：{test_q}\n")
    res = query_gitlab_context(test_q, top_k=3)
    print(format_results(res))