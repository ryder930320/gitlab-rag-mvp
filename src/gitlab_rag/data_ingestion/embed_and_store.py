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

CHUNKS_PATH = "data/chunks_v2.json"
CHROMA_DIR = "chroma_db"
COLLECTION_NAME = "gitlab_rag"
PROGRESS_PATH = "data/embedding_progress.json"

MAX_RETRIES = 3
RETRY_DELAY = 2

# 批次設定
BATCH_SIZE = 32          # 每次 API 呼叫處理的 chunk 數
MAX_TOKENS_PER_ITEM = 300  # 單項截斷上限（字元），對應 ~230 tokens，留安全 margin

# API 速率限制：embedding 100 req/min（官方免費額度）
RATE_LIMIT_CALLS = 100
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
            while self.calls and self.calls[0] <= now - self.window:
                self.calls.popleft()

            if len(self.calls) >= self.max_calls:
                wait_time = self.calls[0] + self.window - now
                if wait_time > 0:
                    time.sleep(wait_time)
                    now = time.time()
                    while self.calls and self.calls[0] <= now - self.window:
                        self.calls.popleft()

            self.calls.append(now)


rate_limiter = RateLimiter(RATE_LIMIT_CALLS, RATE_LIMIT_WINDOW)


def load_progress():
    """載入進度檔，回傳已完成的 chunk_id 集合"""
    if os.path.exists(PROGRESS_PATH):
        with open(PROGRESS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(data.get("done_chunk_ids", []))
    return set()


def save_progress(done_chunk_ids):
    """儲存進度"""
    with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
        json.dump({"done_chunk_ids": sorted(done_chunk_ids)}, f, ensure_ascii=False)


def get_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """
    批次呼叫 NIM embedding API
    Args:
        texts: list of strings (長度 <= BATCH_SIZE)
    Returns:
        list of embeddings (同順序)
    """
    headers = {
        "Authorization": f"Bearer {NIM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": NIM_EMBED_MODEL,
        "input": texts,
        "encoding_format": "float",
        "input_type": "passage",
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            rate_limiter.acquire()
            with httpx.Client(timeout=120.0) as client:
                resp = client.post(NIM_EMBED_URL, headers=headers, json=payload)
                if resp.status_code == 400:
                    error_detail = resp.text
                    print(f"  [400 Bad Request] {error_detail}")
                    if attempt < MAX_RETRIES:
                        # 截斷所有過長的輸入
                        payload["input"] = [t[:MAX_TOKENS_PER_ITEM] for t in texts]
                        print(f"  [重試 {attempt}/{MAX_RETRIES}] 全批次截斷至 {MAX_TOKENS_PER_ITEM} 字元後重試...")
                        time.sleep(RETRY_DELAY * attempt)
                        continue
                if resp.status_code == 429:
                    retry_after = resp.headers.get("Retry-After")
                    wait_time = int(retry_after) if retry_after and retry_after.isdigit() else 10
                    if attempt < MAX_RETRIES:
                        print(f"  ⚠️  Embedding API 速率限制 (HTTP 429)，等待 {wait_time} 秒後重試... (第 {attempt}/{MAX_RETRIES} 次)")
                        time.sleep(wait_time)
                        continue
                    else:
                        raise RuntimeError(f"Embedding API 速率限制 (HTTP 429)，已重試 {MAX_RETRIES} 次仍失敗")
                resp.raise_for_status()
                data = resp.json()
                # 依 data 中的 index 排序確保順序
                embeddings = [None] * len(texts)
                for item in data["data"]:
                    idx = item["index"]
                    embeddings[idx] = item["embedding"]
                return embeddings
        except httpx.TimeoutException:
            if attempt == MAX_RETRIES:
                raise RuntimeError(f"Embedding API 請求逾時 (120 秒)")
            print(f"  [重試 {attempt}/{MAX_RETRIES}] Embedding 逾時")
            time.sleep(RETRY_DELAY * attempt)
        except httpx.HTTPStatusError as e:
            if attempt == MAX_RETRIES:
                raise RuntimeError(f"Embedding API HTTP 錯誤: {e.response.status_code} - {e.response.text}")
            print(f"  [重試 {attempt}/{MAX_RETRIES}] Embedding HTTP 錯誤: {e.response.status_code}")
            time.sleep(RETRY_DELAY * attempt)
        except Exception as e:
            if attempt == MAX_RETRIES:
                raise RuntimeError(f"Embedding API 呼叫失敗: {e}")
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

    # 載入進度
    done_ids = load_progress()
    print(f"已完成: {len(done_ids)} 個 chunks，剩餘: {len(chunks) - len(done_ids)}")

    # 初始化 Chroma
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"}
    )

    # 刪除現有 collection 並重建（確保 metadata 更新）
    client.delete_collection(name=COLLECTION_NAME)
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"}
    )

    existing = collection.count()
    print(f"Chroma 現有筆數: {existing}")

    # 過濾未完成的 chunks
    pending_chunks = [c for c in chunks if c["metadata"]["global_chunk_id"] not in done_ids]
    print(f"待處理: {len(pending_chunks)} 筆")

    if not pending_chunks:
        print("所有 chunks 已完成，無需重跑。")
        return

    start_time = time.time()
    total_done = len(done_ids)

    # 分批處理
    for batch_start in range(0, len(pending_chunks), BATCH_SIZE):
        batch = pending_chunks[batch_start:batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1
        total_batches = (len(pending_chunks) + BATCH_SIZE - 1) // BATCH_SIZE

        print(f"\n=== Batch {batch_num}/{total_batches} ({len(batch)} chunks) ===")

        # 準備輸入 texts
        texts = [c["content"] for c in batch]
        chunk_ids = [c["metadata"]["global_chunk_id"] for c in batch]

        # 呼叫批次 embedding
        try:
            embeddings = get_embeddings_batch(texts)
        except Exception as e:
            print(f"  ❌ Batch 失敗: {e}")
            # 逐個重試（fallback）
            embeddings = []
            for i, text in enumerate(texts):
                try:
                    # 單個重試用舊邏輯（簡化版）
                    single_emb = get_embeddings_batch([text])[0]
                    embeddings.append(single_emb)
                except Exception as e2:
                    print(f"  ❌ Chunk {chunk_ids[i]} 單獨重試也失敗: {e2}")
                    embeddings.append([0.0] * 1024)  # dummy 避免中斷

        # 寫入 Chroma
        ids = [str(cid) for cid in chunk_ids]
        documents = texts
        metadatas = []
        for c in batch:
            meta = c["metadata"]
            meta_entry = {
                "source_type": meta["source_type"],
                "file_path": meta.get("file_path") or "",
                "language": meta.get("language") or "",
                "chunk_index": meta["chunk_index"],
                "created_at": meta.get("created_at") or "",
            }
            if meta.get("source_type") == "code":
                symbols = meta.get("symbols", [])
                symbol_tokens = meta.get("symbol_tokens", [])
                if symbols:
                    meta_entry["symbols"] = symbols
                if symbol_tokens:
                    meta_entry["symbol_tokens"] = symbol_tokens
            metadatas.append(meta_entry)

        collection.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings
        )

        # 更新進度
        for cid in chunk_ids:
            done_ids.add(cid)
        total_done += len(batch)
        save_progress(done_ids)

        elapsed = time.time() - start_time
        rate = total_done / elapsed * 60 if elapsed > 0 else 0
        print(f"  ✅ 完成 {len(batch)} 筆 | 累計 {total_done}/{len(chunks)} | 速度 ~{rate:.0f} chunks/min")

    # 最終驗證
    elapsed = time.time() - start_time
    final_count = collection.count()
    print(f"\n{'='*50}")
    print(f"完成！總耗時: {elapsed:.1f} 秒")
    print(f"Chroma 總筆數: {final_count}")
    print(f"向量維度: {len(embeddings[0]) if embeddings else 0}")

    # 隨機抽查
    import random
    all_ids = [str(c["metadata"]["global_chunk_id"]) for c in chunks]
    sample = collection.get(ids=[random.choice(all_ids)], include=["embeddings", "documents", "metadatas"])
    print(f"\n抽查驗證:")
    print(f"  ID: {sample['ids'][0]}")
    print(f"  Metadata: {sample['metadatas'][0]}")
    print(f"  向量維度: {len(sample['embeddings'][0])}")
    print(f"  內容前 100 字: {sample['documents'][0][:100]}...")


if __name__ == "__main__":
    main()