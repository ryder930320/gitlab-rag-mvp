"""Reranker 整合 (CP-24)

在 hybrid_search 之後、confidence_evaluator 之前，加入一層 reranker。
使用 NIM Nemotron-3-Ultra 進行生成式重排序（因為 NIM 免費額度沒有專用 rerank endpoint 可用）。
"""
import os
import json
import time
import httpx
from typing import List, Dict, Any
from dotenv import load_dotenv

load_dotenv()

NIM_API_KEY = os.getenv("NIM_API_KEY")
NIM_GENERATE_MODEL = os.getenv("NIM_GENERATE_MODEL", "nvidia/nemotron-3-ultra-550b-a55b")
NIM_GENERATE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

# 匯入 logger
from .nim_logger import log_nim_call


def _call_nim_rerank(query: str, passages: List[str], timeout: float = 60.0) -> List[Dict[str, Any]]:
    """呼叫 NIM 生成模型進行重排序"""
    if not NIM_API_KEY:
        raise RuntimeError("請先設定 .env 中的 NIM_API_KEY")

    # 建構 rerank prompt
    passages_text = "\n\n".join([f"Passage {i}: {p}" for i, p in enumerate(passages)])
    prompt = f"""你是一個重排序模型。給定一個查詢和多個段落，請根據與查詢的相關性對段落進行排序。

查詢：{query}

段落：
{passages_text}

請輸出 JSON 陣列，每個元素包含 index（原始段落索引 0-based）和 score（相關性分數 0-1，越高越相關）。
按 score 降序排列。只輸出 JSON 陣列，不要額外文字。

輸出格式範例：
[{{"index": 2, "score": 0.95}}, {{"index": 0, "score": 0.8}}, {{"index": 1, "score": 0.3}}]"""

    headers = {
        "Authorization": f"Bearer {NIM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": NIM_GENERATE_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 1024,
        "stream": False,
    }

    start = time.time()
    error_msg = None
    response_json = None
    status_code = 0
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(NIM_GENERATE_URL, headers=headers, json=payload)
            latency_ms = int((time.time() - start) * 1000)
            status_code = resp.status_code
            if resp.status_code == 402:
                raise RuntimeError("NIM API 額度用盡或帳單問題 (HTTP 402)")
            if resp.status_code == 429:
                raise RuntimeError("NIM API 速率限制 (HTTP 429)，請稍後再試")
            resp.raise_for_status()
            data = resp.json()
            response_json = data
            content = data["choices"][0]["message"]["content"].strip()

            # 解析 JSON
            try:
                ranked = json.loads(content)
            except json.JSONDecodeError:
                # 嘗試提取 JSON 部分
                import re
                match = re.search(r'\[.*\]', content, re.DOTALL)
                if match:
                    ranked = json.loads(match.group())
                else:
                    raise RuntimeError(f"Reranker 回應非 JSON 格式: {content[:200]}")

            # 驗證格式
            if not isinstance(ranked, list):
                raise RuntimeError("Reranker 回應不是列表")

            for item in ranked:
                if "index" not in item or "score" not in item:
                    raise RuntimeError("Reranker 回應缺少 index 或 score")

            return ranked

    except httpx.TimeoutException:
        latency_ms = int((time.time() - start) * 1000)
        raise RuntimeError(f"NIM API 請求逾時 ({timeout} 秒)")
    except httpx.HTTPStatusError as e:
        latency_ms = int((time.time() - start) * 1000)
        status_code = e.response.status_code
        error_msg = str(e)
        raise RuntimeError(f"NIM API HTTP 錯誤: {e.response.status_code} - {e.response.text}")
    except Exception as e:
        latency_ms = int((time.time() - start) * 1000)
        error_msg = str(e)
        raise RuntimeError(f"NIM API 呼叫失敗: {e}")
    finally:
        log_nim_call(
            query=query,
            model=NIM_GENERATE_MODEL,
            call_type="rerank",
            request_payload=payload,
            response_payload=response_json,
            finish_reason=None,
            fallback_triggered=False,  # _call_nim_rerank 本身不負責 fallback，由上層決定
            latency_ms=latency_ms,
            error=error_msg,
            status_code=status_code,
        )


def rerank_results(
    query: str,
    candidates: List[Dict[str, Any]],
    top_k: int = 5,
    enabled: bool = True,
) -> List[Dict[str, Any]]:
    """
    對 hybrid_search 回傳的候選結果進行 reranking。

    Args:
        query: 原始查詢字串
        candidates: hybrid_search 回傳的結果列表（已按 RRF 排序）
        top_k: 最終回傳數量
        enabled: 是否啟用 reranker（可透過環境變數關閉）

    Returns:
        重新排序後的結果列表，新增 rerank_score 與 rerank_rank 欄位
    """
    if not enabled or not candidates:
        # 不啟用或無候選，直接回傳原順序並補上欄位
        for i, c in enumerate(candidates[:top_k]):
            c["rerank_score"] = c.get("rrf_score", 0.0)
            c["rerank_rank"] = i + 1
        return candidates[:top_k]

    # 準備段落內容
    passages = [c["content"] for c in candidates]

    try:
        ranked = _call_nim_rerank(query, passages)
    except RuntimeError as e:
        print(f"[Reranker] 呼叫失敗，回退到 RRF 排序: {e}")
        # 記錄 fallback 事件
        log_nim_call(
            query=query,
            model=NIM_GENERATE_MODEL,
            call_type="rerank",
            request_payload={"model": NIM_GENERATE_MODEL, "messages": [{"role": "user", "content": f"rerank fallback for: {query}"}]},
            response_payload={"fallback_to": "rrf", "reason": str(e)},
            finish_reason=None,
            fallback_triggered=True,
            latency_ms=0,
            error=str(e),
            status_code=0,
        )
        for i, c in enumerate(candidates[:top_k]):
            c["rerank_score"] = c.get("rrf_score", 0.0)
            c["rerank_rank"] = i + 1
        return candidates[:top_k]

    # 建立 index -> rerank_score 映射
    rerank_scores = {item["index"]: item["score"] for item in ranked}

    # 將 rerank 分數加入候選項
    for i, cand in enumerate(candidates):
        cand["rerank_score"] = rerank_scores.get(i, 0.0)

    # 按 rerank_score 重新排序
    reranked = sorted(candidates, key=lambda x: x["rerank_score"], reverse=True)

    # 更新 rerank_rank 為新排序後的名次
    for i, cand in enumerate(reranked):
        cand["rerank_rank"] = i + 1

    return reranked[:top_k]


if __name__ == "__main__":
    # 簡單測試
    test_query = "如何建立 whl 安裝包？"
    test_passages = [
        "from setuptools import setup, find_packages\nsetup(name='mypkg', packages=find_packages())",
        "def hello():\n    print('hello world')",
        "python setup.py bdist_wheel\npip install dist/mypkg-0.1.whl",
        "import torch\nmodel = torch.nn.Linear(10, 1)",
    ]

    print("測試 Reranker...")
    result = _call_nim_rerank(test_query, test_passages)
    print(f"排序結果: {result}")