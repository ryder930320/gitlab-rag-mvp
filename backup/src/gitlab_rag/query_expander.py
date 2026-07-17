"""查詢擴展：用小型 LLM 將純中文查詢擴展為「原始問題 + 猜測的英文技術詞彙」
只餵給 BM25/符號匹配路徑，向量檢索與最終生成 prompt 仍使用原始問題 (CP-23)
"""
import os
import json
import httpx
import re
from typing import List, Dict, Optional
from dotenv import load_dotenv
from pathlib import Path

# 明確指定 .env 路徑
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(ENV_PATH)

NIM_API_KEY = os.getenv("NIM_API_KEY")
# 使用較小/較快的模型做查詢擴展，節省額度與延遲
NIM_EXPAND_MODEL = os.getenv("NIM_EXPAND_MODEL", "nvidia/nemotron-3-ultra-550b-a55b")
NIM_GENERATE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"


def _call_nim_expand(prompt: str, timeout: float = 30.0) -> str:
    """呼叫 NIM 生成模型進行查詢擴展"""
    if not NIM_API_KEY:
        raise RuntimeError("請先設定 .env 中的 NIM_API_KEY")

    headers = {
        "Authorization": f"Bearer {NIM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": NIM_EXPAND_MODEL,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,  # 低溫度，追求確定性
        "max_tokens": 512,
        "stream": False,
    }

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(NIM_GENERATE_URL, headers=headers, json=payload)
            if resp.status_code == 402:
                raise RuntimeError("NIM API 額度用盡或帳單問題 (HTTP 402)")
            if resp.status_code == 429:
                raise RuntimeError("NIM API 速率限制 (HTTP 429)，請稍後再試")
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
    except httpx.TimeoutException:
        raise RuntimeError(f"NIM API 請求逾時 ({timeout} 秒)")
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"NIM API HTTP 錯誤: {e.response.status_code} - {e.response.text}")
    except Exception as e:
        raise RuntimeError(f"NIM API 呼叫失敗: {e}")


def _build_expansion_prompt(query: str) -> str:
    """建構查詢擴展 prompt"""
    return f"""你是一個技術術語翻譯助手。給定一個純中文的程式設計相關查詢，請推測該查詢可能涉及的英文技術關鍵字（函式名、類別名、變數名、檔名、技術術語等）。

規則：
1. 只輸出英文技術詞彙，用空格分隔，不要輸出中文、不要輸出句子、不要解釋
2. 詞彙需為該查詢語境下合理的程式碼符號或技術術語
3. 若查詢已包含足夠英文技術詞彙，直接輸出 "SKIP"
4. 最多輸出 10 個詞彙

查詢：{query}

英文技術詞彙："""


def _has_enough_english_terms(query: str) -> bool:
    """判斷查詢是否已包含足夠英文技術詞彙，可跳過擴展"""
    # 提取查詢中的英文單詞（長度>=2）
    english_words = re.findall(r'[a-zA-Z]{2,}', query)
    # 如果有 3 個以上英文詞，視為已足夠
    if len(english_words) >= 3:
        return True
    # 檢查是否有程式碼風格（底線、駝峰、常見技術縮寫）
    # 注意：camelCase 檢查不使用 IGNORECASE，避免誤判全小寫縮寫
    if re.search(r'[a-z]+_[a-z]+', query):  # snake_case
        return True
    if re.search(r'[a-z]+[A-Z][a-zA-Z]+', query):  # camelCase (區分大小寫)
        return True
    tech_abbrevs = r'\b(gpio|api|sdk|ide|ci|cd|ai|ml|dl|ui|ux|db|sql|http|rest|grpc|tcp|udp|ssh|ssl|tls)\b'
    if re.search(tech_abbrevs, query, re.IGNORECASE):
        return True
    return False


def expand_chinese_query(query: str) -> Dict[str, any]:
    """
    擴展純中文查詢，回傳擴展後的英文技術詞彙

    Returns:
        {
            "original_query": str,
            "expanded_terms": List[str],  # 擴展出的英文詞彙
            "expanded_query_for_bm25": str,  # 原始查詢 + 擴展詞彙（供 BM25/符號路徑使用）
            "skipped": bool,  # 是否跳過擴展
            "skip_reason": str,
            "api_latency_ms": float,
        }
    """
    import time

    result = {
        "original_query": query,
        "expanded_terms": [],
        "expanded_query_for_bm25": query,
        "skipped": False,
        "skip_reason": "",
        "api_latency_ms": 0.0,
    }

    # 1. 先判斷是否需要擴展
    if _has_enough_english_terms(query):
        result["skipped"] = True
        result["skip_reason"] = "查詢已包含足夠英文技術詞彙"
        return result

    # 2. 呼叫 LLM 擴展
    prompt = _build_expansion_prompt(query)
    start_time = time.time()
    try:
        response = _call_nim_expand(prompt)
        result["api_latency_ms"] = (time.time() - start_time) * 1000

        if response.strip().upper() == "SKIP":
            result["skipped"] = True
            result["skip_reason"] = "LLM 判斷無需擴展"
            return result

        # 解析回傳的英文詞彙（空格分隔）
        terms = [t.strip() for t in response.split() if t.strip()]
        # 過濾：只保留合法的英文技術詞彙（字母、數字、底線、連字號）
        valid_terms = []
        for t in terms:
            if re.match(r'^[a-zA-Z0-9_\-]+$', t) and len(t) >= 2:
                valid_terms.append(t.lower())

        # 去重並限制數量
        seen = set()
        unique_terms = []
        for t in valid_terms:
            if t not in seen:
                seen.add(t)
                unique_terms.append(t)
        unique_terms = unique_terms[:10]

        result["expanded_terms"] = unique_terms
        if unique_terms:
            result["expanded_query_for_bm25"] = f"{query} {' '.join(unique_terms)}"

    except RuntimeError as e:
        result["api_latency_ms"] = (time.time() - start_time) * 1000
        result["skipped"] = True
        result["skip_reason"] = f"API 呼叫失敗: {e}"
        # 失敗時回退到原始查詢

    return result


def demo():
    """示範：測試幾個純中文查詢"""
    test_queries = [
        "危險區域",
        "專案打包",
        "專案編譯流程",
        "推論引擎 裝置設定",
        "how to set device",  # 應該跳過
        "available devices list",  # 應該跳過
        "建立 whl 安裝包",
        "GPIO 控制怎麼用",
    ]

    for q in test_queries:
        print(f"\n{'='*60}")
        print(f"查詢: {q}")
        print(f"{'='*60}")
        result = expand_chinese_query(q)
        print(f"跳過: {result['skipped']} ({result['skip_reason']})")
        print(f"擴展詞彙: {result['expanded_terms']}")
        print(f"BM25用查詢: {result['expanded_query_for_bm25']}")
        print(f"API延遲: {result['api_latency_ms']:.0f} ms")


if __name__ == "__main__":
    demo()