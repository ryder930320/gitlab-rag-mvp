"""符號自動映射：從 symbols 拆字為 tokens，查詢時以英文詞匹配 tokens 給加分 (CP-12)"""
import re
from typing import List, Set, Dict
from pathlib import Path


def split_identifier(identifier: str) -> List[str]:
    """將駝峰式/底線命名拆解為 tokens
    e.g. 'available_devices' -> ['available', 'devices']
         'compileModel' -> ['compile', 'model']
         'AI_Core' -> ['ai', 'core']
         'inferBase' -> ['infer', 'base']
    """
    # 先按底線分割
    parts = identifier.split('_')
    tokens = []
    for part in parts:
        # 再按駝峰式分割：小寫字母接大寫字母的邊界
        # e.g., 'compileModel' -> ['compile', 'Model']
        sub_parts = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', part).split()
        tokens.extend([p.lower() for p in sub_parts])
    # 過濾太短的 token（單字母通常無意義）
    return [t for t in tokens if len(t) >= 2]


def extract_symbol_tokens(symbols: List[str]) -> Set[str]:
    """從 symbols 列表抽取所有 tokens，去重並轉小寫"""
    tokens = set()
    for sym in symbols:
        tokens.update(split_identifier(sym))
    return tokens


def build_symbol_token_index(chunks: List[dict]) -> Dict[str, Set[str]]:
    """為所有 chunks 建立 symbol_tokens 索引，key 為 chunk_id"""
    index = {}
    for chunk in chunks:
        meta = chunk.get("metadata", {})
        chunk_id = str(meta.get("global_chunk_id", chunk.get("chunk_index", 0)))
        symbols = meta.get("symbols", [])
        # 也把檔名加入 symbols（keyword_index.py 已經做了，但這裡再保險處理一次）
        file_path = meta.get("file_path", "")
        if file_path:
            fname = Path(file_path).stem
            symbols = list(symbols) + [fname]
        index[chunk_id] = extract_symbol_tokens(symbols)
    return index


def symbol_token_bonus(query: str, symbol_tokens: Set[str], bonus: float = 0.2) -> float:
    """查詢中的英文詞若命中 symbol_tokens，給予 bonus
    - 將查詢按非字母數字切分，取英文單詞（長度>=2）
    - 若任一單詞在 symbol_tokens 中，回傳 bonus
    """
    if not symbol_tokens:
        return 0.0
    # 提取查詢中的英文單詞（忽略中文、數字、符號）
    query_words = set(re.findall(r'[a-zA-Z]{2,}', query.lower()))
    # 檢查交集
    if query_words & symbol_tokens:
        return bonus
    return 0.0


def demo():
    """示範：展示 symbol 拆解效果"""
    test_symbols = [
        "read_json", "read_hazard_json", "list_to_tuple",
        "GPIO", "get_dio_status", "set_dio_status",
        "AI_Core", "infer_base", "available_devices",
        "compile_model", "visualization", "Infer",
        "device_controll", "build_pyd"
    ]
    tokens = extract_symbol_tokens(test_symbols)
    print("=== Symbol Tokens ===")
    for t in sorted(tokens):
        print(f"  {t}")
    
    # 測試查詢匹配
    test_queries = [
        "推論引擎 裝置設定",
        "how to set device",
        "available devices list",
        "compile model",
        "GPIO 控制",
    ]
    print("\n=== Query Match Test ===")
    for q in test_queries:
        b = symbol_token_bonus(q, tokens)
        matched = set(re.findall(r'[a-zA-Z]{2,}', q.lower())) & tokens
        print(f"  query='{q}' -> bonus={b}, matched={matched}")


if __name__ == "__main__":
    demo()