"""BM25 關鍵字索引建立 (CP-8)"""
import json
import re
import pickle
from pathlib import Path
from rank_bm25 import BM25Okapi
from typing import List, Dict, Any


CHUNKS_PATH = "data/chunks.json"
INDEX_PATH = "data/bm25_index.pkl"


# 符號抽取正則
FUNC_PATTERN = re.compile(r"def\s+(\w+)\s*\(")
CLASS_PATTERN = re.compile(r"class\s+(\w+)\s*[:\(]")
JS_FUNC_PATTERN = re.compile(r"function\s+(\w+)\s*\(")
JS_CONST_FUNC_PATTERN = re.compile(r"const\s+(\w+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>")


def extract_symbols(content: str, language: str) -> List[str]:
    """從程式碼內容抽取函式/類別名稱作為符號"""
    symbols = []

    if language in ("py", "python"):
        symbols += FUNC_PATTERN.findall(content)
        symbols += CLASS_PATTERN.findall(content)
    elif language in ("js", "javascript", "ts", "typescript"):
        symbols += JS_FUNC_PATTERN.findall(content)
        symbols += JS_CONST_FUNC_PATTERN.findall(content)
        # 也抓 class
        symbols += CLASS_PATTERN.findall(content)

    # 去重並保持順序
    seen = set()
    unique = []
    for s in symbols:
        if s not in seen:
            seen.add(s)
            unique.append(s)
    return unique


def tokenize(text: str) -> List[str]:
    """簡單 tokenizer：小寫、按非字母數字切分"""
    return re.findall(r"\w+", text.lower())


def main():
    # 1. 讀取 chunks
    with open(CHUNKS_PATH, "r", encoding="utf-8") as f:
        chunks = json.load(f)

    print(f"讀取 {len(chunks)} 個 chunks")

    # 2. 為程式碼 chunk 抽取符號，更新 metadata
    for chunk in chunks:
        meta = chunk.get("metadata", {})
        if meta.get("source_type") == "code":
            content = chunk["content"]
            lang = meta.get("language", "")
            symbols = extract_symbols(content, lang)
            meta["symbols"] = symbols

            # 檔案名也加入符號（不含副檔名）
            file_path = meta.get("file_path", "")
            if file_path:
                fname = Path(file_path).stem
                if fname not in symbols:
                    symbols.append(fname)

    # 3. 建立 BM25 索引用的 corpus（每個 chunk 的文字內容 tokenize）
    corpus = [tokenize(chunk["content"]) for chunk in chunks]

    bm25 = BM25Okapi(corpus)

    # 4. 序列化存檔
    index_data = {
        "bm25": bm25,
        "chunks": chunks,  # 保留完整 chunk 資料供後續檢索使用
    }

    Path(INDEX_PATH).parent.mkdir(parents=True, exist_ok=True)
    with open(INDEX_PATH, "wb") as f:
        pickle.dump(index_data, f)

    print(f"BM25 索引已存至 {INDEX_PATH}")
    print(f"索引筆數: {len(corpus)}")

    # 5. 隨機抽查 2 個程式碼 chunk 的 symbols
    import random
    code_chunks = [c for c in chunks if c["metadata"].get("source_type") == "code"]
    samples = random.sample(code_chunks, min(2, len(code_chunks)))

    print("\n=== 符號抽取抽查 ===")
    for s in samples:
        meta = s["metadata"]
        print(f"\nFile: {meta.get('file_path')} | Chunk: {meta.get('chunk_index')}")
        print(f"Language: {meta.get('language')}")
        print(f"Symbols: {meta.get('symbols', [])}")
        print(f"Content preview: {s['content'][:150]}...")


if __name__ == "__main__":
    main()