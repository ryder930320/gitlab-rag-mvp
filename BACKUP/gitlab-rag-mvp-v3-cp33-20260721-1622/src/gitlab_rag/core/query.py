import os
import json
import httpx
from dotenv import load_dotenv
import chromadb

load_dotenv()

NIM_API_KEY = os.getenv("NIM_API_KEY")
NIM_EMBED_MODEL = os.getenv("NIM_EMBED_MODEL")
NIM_EMBED_URL = "https://integrate.api.nvidia.com/v1/embeddings"

CHROMA_DIR = "chroma_db"
COLLECTION_NAME = "gitlab_rag"


def get_embedding(text: str) -> list[float]:
    """呼叫 NIM embedding API（query 用 input_type=query）"""
    headers = {
        "Authorization": f"Bearer {NIM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": NIM_EMBED_MODEL,
        "input": text,
        "encoding_format": "float",
        "input_type": "query"  # asymmetric model: query vs passage
    }

    with httpx.Client(timeout=120.0) as client:
        resp = client.post(NIM_EMBED_URL, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["data"][0]["embedding"]


def query_chroma(question: str, top_k: int = 5) -> list[dict]:
    """檢索 top-k 相似 chunks"""
    # 1. Embed question
    query_embedding = get_embedding(question)

    # 2. 查詢 Chroma
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    collection = client.get_collection(COLLECTION_NAME)

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"]
    )

    # 3. 整理輸出
    hits = []
    for i in range(len(results["ids"][0])):
        hits.append({
            "content": results["documents"][0][i],
            "file_path": results["metadatas"][0][i].get("file_path", ""),
            "source_type": results["metadatas"][0][i].get("source_type", ""),
            "language": results["metadatas"][0][i].get("language", ""),
            "chunk_index": results["metadatas"][0][i].get("chunk_index", 0),
            "created_at": results["metadatas"][0][i].get("created_at", ""),
            "score": 1.0 - results["distances"][0][i],  # cosine similarity
        })
    return hits


def main():
    # 5 組測試問題（依實際 repo 內容設計）
    test_questions = [
        "這個專案怎麼處理 GPIO 控制？",
        "如何將 Python 腳本打包成 .pyd 二進位檔案？",
        "專案使用什麼推論引擎？怎麼設定裝置？",
        "危險區域偵測是如何實作的？",
        "如何建立 whl 安裝包？",
    ]

    print("=" * 60)
    print("GitLab RAG MVP - 檢索測試")
    print("=" * 60)

    for idx, q in enumerate(test_questions, 1):
        print(f"\n【測試 {idx}】問題：{q}")
        print("-" * 60)

        hits = query_chroma(q, top_k=5)

        for rank, h in enumerate(hits, 1):
            print(f"\n  Top-{rank} (score={h['score']:.4f})")
            print(f"    Type: {h['source_type']} | File: {h['file_path']} | Chunk: {h['chunk_index']}")
            if h['created_at']:
                print(f"    Commit: {h['created_at']}")
            preview = h['content'][:150].replace('\n', ' ')
            print(f"    Content: {preview}...")

    print("\n" + "=" * 60)
    print("檢索測試完成")
    print("=" * 60)


if __name__ == "__main__":
    main()