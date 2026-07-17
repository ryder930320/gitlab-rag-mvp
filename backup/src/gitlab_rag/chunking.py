import json
import os

DATA_DIR = "data"
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150
CODE_EXTS = {".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".cpp", ".c", ".h", ".cs", ".go", ".rs", ".rb", ".php", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf"}


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """固定長度切分，保留重疊"""
    if len(text) <= chunk_size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return chunks


def main():
    with open(os.path.join(DATA_DIR, "raw_files.json"), "r", encoding="utf-8") as f:
        raw_files = json.load(f)
    with open(os.path.join(DATA_DIR, "raw_commits.json"), "r", encoding="utf-8") as f:
        raw_commits = json.load(f)

    chunks = []
    chunk_idx = 0

    # 程式碼檔案切分
    for item in raw_files:
        path = item["path"]
        content = item["content"]
        lang = item.get("language", "")
        code_chunks = chunk_text(content)
        for i, ch in enumerate(code_chunks):
            chunks.append({
                "content": ch,
                "metadata": {
                    "source_type": "code",
                    "file_path": path,
                    "language": lang,
                    "chunk_index": i,
                    "global_chunk_id": chunk_idx
                }
            })
            chunk_idx += 1

    # commit 每筆為一個 chunk
    for i, commit in enumerate(raw_commits):
        full_msg = f"{commit['title']}\n{commit['message']}".strip()
        chunks.append({
            "content": full_msg,
            "metadata": {
                "source_type": "commit",
                "file_path": None,
                "language": None,
                "chunk_index": 0,
                "global_chunk_id": chunk_idx,
                "created_at": commit.get("created_at", "")
            }
        })
        chunk_idx += 1

    os.makedirs(DATA_DIR, exist_ok=True)
    out_path = os.path.join(DATA_DIR, "chunks.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)

    # 統計
    code_chunks = sum(1 for c in chunks if c["metadata"]["source_type"] == "code")
    commit_chunks = sum(1 for c in chunks if c["metadata"]["source_type"] == "commit")
    print(f"總 chunk 數: {len(chunks)}")
    print(f"  程式碼 chunk: {code_chunks}")
    print(f"  commit chunk: {commit_chunks}")
    print(f"輸出: {out_path}")

    # 隨機抽查 3 個
    import random
    samples = random.sample(chunks, min(3, len(chunks)))
    print("\n--- 抽查 3 個 chunk ---")
    for s in samples:
        meta = s["metadata"]
        print(f"\n[chunk_id={meta['global_chunk_id']}] type={meta['source_type']} file={meta['file_path']} idx={meta['chunk_index']}")
        print(f"長度: {len(s['content'])} 字元")
        print(s["content"][:200] + ("..." if len(s["content"]) > 200 else ""))


if __name__ == "__main__":
    main()