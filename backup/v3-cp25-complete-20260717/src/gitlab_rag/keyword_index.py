"""BM25 關鍵字索引建立 (CP-8) - 修正版：加入 symbol_tokens (CP-12)、擴充符號抽取 (CP-14)"""
import json
import re
import pickle
from pathlib import Path
from rank_bm25 import BM25Okapi
from typing import List, Dict, Any


CHUNKS_PATH = "data/chunks.json"
INDEX_PATH = "data/bm25_index.pkl"


# 符號抽取正則（CP-8 原有 + CP-14 新增）
FUNC_PATTERN = re.compile(r"def\s+(\w+)\s*\(")
CLASS_PATTERN = re.compile(r"class\s+(\w+)\s*[:\\(]")
JS_FUNC_PATTERN = re.compile(r"function\s+(\w+)\s*\(")
JS_CONST_FUNC_PATTERN = re.compile(r"const\s+(\w+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>")

# CP-14 新增：import、方法呼叫、常數
# from 模組 import 名稱1, 名稱2（單行）
IMPORT_FROM_PATTERN = re.compile(r"^from\s+([\w.]+)\s+import\s+([^\n]+)\s*$", re.MULTILINE)
# import 模組1, 模組2（單行，不含 from）- 禁止換行，支援 as 別名
IMPORT_SIMPLE_PATTERN = re.compile(r"^\s*import\s+([^\n]+)\s*$", re.MULTILINE)
# 方法呼叫：obj.method()
CALL_PATTERN = re.compile(r"(\w+)\.(\w+)\s*\(")
# 常數：全大寫開頭的賦值（行首或縮進後）
CONST_PATTERN = re.compile(r"(?:^|\n)\s*([A-Z_][A-Z0-9_]*)\s*=")


def extract_symbols(content: str, language: str) -> List[str]:
    """從程式碼內容抽取函式/類別名稱作為符號 (CP-14 擴充：import、呼叫、常數)"""
    symbols = []

    if language in ("py", "python"):
        symbols += FUNC_PATTERN.findall(content)
        symbols += CLASS_PATTERN.findall(content)
        # CP-14: import
        for match in IMPORT_FROM_PATTERN.findall(content):
            symbols.append(match[0])  # 模組名
            # 也加入被 import 的名稱
            for name in match[1].split(','):
                n = name.strip()
                if n and n != '*':
                    symbols.append(n)
        for match in IMPORT_SIMPLE_PATTERN.findall(content):
            for name in match.split(','):
                n = name.strip()
                if n:
                    symbols.append(n)
        # CP-14: 方法呼叫 - 抽取被呼叫的方法名
        for match in CALL_PATTERN.findall(content):
            symbols.append(match[1])  # method name
        # CP-14: 常數
        for match in CONST_PATTERN.findall(content):
            symbols.append(match)
    elif language in ("js", "javascript", "ts", "typescript"):
        symbols += JS_FUNC_PATTERN.findall(content)
        symbols += JS_CONST_FUNC_PATTERN.findall(content)
        symbols += CLASS_PATTERN.findall(content)

    # 去重並保持順序
    seen = set()
    unique = []
    for s in symbols:
        if s not in seen:
            seen.add(s)
            unique.append(s)
    return unique


def split_symbol(symbol: str) -> List[str]:
    """
    將符號拆解為 tokens (CP-12)
    - 駝峰命名: getDioStatus -> ['get', 'dio', 'status']
    - 底線命名: get_dio_status -> ['get', 'dio', 'status']
    - 全小寫
    """
    if not symbol:
        return []
    # 先處理駝峰：在大寫字母前插入空格
    s1 = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", symbol)
    # 再按底線和非字母數字分割
    tokens = re.split(r"[_\\W]+", s1)
    # 全部轉小寫，過濾空字串和單字母
    return [t.lower() for t in tokens if len(t) > 1]


def extract_symbol_tokens(symbols: List[str]) -> List[str]:
    """從符號列表提取所有 tokens，去重"""
    tokens = []
    for sym in symbols:
        tokens.extend(split_symbol(sym))
    # 去重
    seen = set()
    unique = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            unique.append(t)
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
            
            # CP-12: 從符號提取 tokens
            meta["symbol_tokens"] = extract_symbol_tokens(symbols)

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

    # 5. 隨機抽查 3 個程式碼 chunk 的 symbols 和 symbol_tokens (CP-12: 3個而非2個)
    import random
    code_chunks = [c for c in chunks if c["metadata"].get("source_type") == "code"]
    samples = random.sample(code_chunks, min(3, len(code_chunks)))

    print("\n=== 符號抽取抽查 (含 symbol_tokens) ===")
    for s in samples:
        meta = s["metadata"]
        print(f"\nFile: {meta.get('file_path')} | Chunk: {meta.get('chunk_index')}")
        print(f"Language: {meta.get('language')}")
        print(f"Symbols: {meta.get('symbols', [])}")
        print(f"Symbol Tokens: {meta.get('symbol_tokens', [])}")
        print(f"Content preview: {s['content'][:150]}...")


if __name__ == "__main__":
    main()