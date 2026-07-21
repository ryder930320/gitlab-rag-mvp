import os
import json
import time
import httpx
import threading
from collections import deque
from dotenv import load_dotenv
import chromadb

load_dotenv()

NIM_API_KEY = os.getenv("NIM_API_KEY")
NIM_EMBED_MODEL = os.getenv("NIM_EMBED_MODEL")
NIM_EMBED_URL = "https://integrate.api.nvidia.com/v1/embeddings"

CHUNKS_PATH = "data/chunks.json"
CHROMA_DIR = "chroma_db"
COLLECTION_NAME = "gitlab_rag"
MAX_RETRIES = 3
RETRY_DELAY = 2

# API 速率限制：32 次/分鐘
RATE_LIMIT_CALLS = 32
RATE_LIMIT_WINDOW = 60.0  # 秒


class RateLimiter:
    """Thread-safe sliding window rate limiter"""

    def __init__(self, max_calls: int, window_seconds: float):
        self.max_calls = max_calls
        self.window = window_seconds
        self.calls = deque()
        self.lock = threading.Lock()

    def acquire(self):
        with self.lock:
            now = time.time()
            # 移除窗口外的呼叫記錄
            while self.calls and self.calls[0] <= now - self.window:
                self.calls.popleft()

            if len(self.calls) >= self.max_calls:
                # 需要等待最舊的呼叫離開窗口
                wait_time = self.calls[0] + self.window - now
                if wait_time > 0:
                    time.sleep(wait_time)
                    now = time.time()
                    while self.calls and self.calls[0] <= now - self.window:
                        self.calls.popleft()

            self.calls.append(now)


rate_limiter = RateLimiter(RATE_LIMIT_CALLS, RATE_LIMIT_WINDOW)


def get_embedding(text: str) -> list[float]:
    """呼叫 NIM embedding API，含重試機制與速率限制"""
    headers = {
        "Authorization": f"Bearer {NIM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": NIM_EMBED_MODEL,
        "input": text,
        "encoding_format": "float",
        "input_type": "passage"  # required for asymmetric models like nv-embedqa-e5-v5
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            rate_limiter.acquire()  # 速率限制
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(NIM_EMBED_URL, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                return data["data"][0]["embedding"]
        except Exception as e:
            if attempt == MAX_RETRIES:
                raise
            print(f"  [重試 {attempt}/{MAX_RETRIES}] Embedding 失敗: {e}")
            time.sleep(RETRY_DELAY * attempt)

    raise RuntimeError("Embedding failed after retries")


def main():
    if not NIM_API_KEY or not NIM_EMBED_MODEL:
        raise RuntimeError("請先設定 .env 中的 NIM_API_KEY 和 NIM_EMBED_MODEL")

    # 讀取 chunks
    with open(CHUNKS_PATH, "r", encoding="utf-8") as f:
        chunks = json.load(f)

    print(f"讀取 {len(chunks)} 個 chunks")

    # 初始化 Chroma
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"}
    )

    # 檢查現有數量
    existing = collection.count()
    print(f"Chroma 現有筆數: {existing}")

    # 準備批次寫入
    ids = []
    documents = []
    metadatas = []
    embeddings = []

    start_time = time.time()

    for i, chunk in enumerate(chunks):
        content = chunk["content"]
        meta = chunk["metadata"]

        print(f"[{i+1}/{len(chunks)}] Embedding chunk_id={meta['global_chunk_id']} ({meta['source_type']})...")

        embedding = get_embedding(content)

        ids.append(str(meta["global_chunk_id"]))
        documents.append(content)
        metadatas.append({
            "source_type": meta["source_type"],
            "file_path": meta.get("file_path") or "",
            "language": meta.get("language") or "",
            "chunk_index": meta["chunk_index"],
            "created_at": meta.get("created_at") or ""
        })
        embeddings.append(embedding)

        # 速率限制已由 RateLimiter 處理，移除固定 sleep

    # 批次寫入 Chroma
    collection.add(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
        embeddings=embeddings
    )

    elapsed = time.time() - start_time
    final_count = collection.count()
    dim = len(embeddings[0]) if embeddings else 0

    print(f"\n完成！")
    print(f"寫入筆數: {len(chunks)}")
    print(f"Chroma 總筆數: {final_count}")
    print(f"向量維度: {dim}")
    print(f"耗時: {elapsed:.1f} 秒")

    # 隨機抽查 1 筆
    import random
    sample = collection.get(ids=[random.choice(ids)], include=["embeddings", "documents", "metadatas"])
    print(f"\n抽查驗證:")
    print(f"  ID: {sample['ids'][0]}")
    print(f"  Metadata: {sample['metadatas'][0]}")
    print(f"  向量維度: {len(sample['embeddings'][0])}")
    print(f"  內容前 100 字: {sample['documents'][0][:100]}...")


if __name__ == "__main__":
    main()