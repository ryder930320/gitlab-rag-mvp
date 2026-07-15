"""生成程式碼建議整合 (CP-18)

完整流程：
1. 呼叫 query_gitlab_context() 取得檢索結果
2. 呼叫 evaluate_confidence() 取得信心等級
3. 呼叫 build_prompt() 組出生成用 prompt
4. 呼叫 NIM 生成模型 (deepseek-v4-flash 或指定模型) 產生建議文字
5. 組合回傳：
   {
     "suggestion": str,          # 生成的建議內容
     "confidence": str,          # high/medium/low
     "confidence_reason": str,
     "sources": list[dict],      # 引用的 chunk 來源（檔名、片段）
   }
"""
import os
import httpx
from typing import List, Dict, Any
from dotenv import load_dotenv

load_dotenv()

NIM_API_KEY = os.getenv("NIM_API_KEY")
NIM_GENERATE_MODEL = os.getenv("NIM_GENERATE_MODEL", "nvidia/nemotron-3-ultra-550b-a55b")
NIM_GENERATE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

from rag_interface import query_gitlab_context
from confidence_evaluator import evaluate_confidence
from prompt_builder import build_prompt


def call_nim_generate(prompt: str, timeout: float = 60.0) -> str:
    """
    呼叫 NIM 生成模型 API。

    Args:
        prompt: 完整 prompt 字串
        timeout: 請求逾時秒數

    Returns:
        生成的文字內容

    Raises:
        RuntimeError: API 錯誤、額度用盡、timeout 等
    """
    if not NIM_API_KEY:
        raise RuntimeError("請先設定 .env 中的 NIM_API_KEY")

    headers = {
        "Authorization": f"Bearer {NIM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": NIM_GENERATE_MODEL,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2,
        "max_tokens": 4096,
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


def generate_coding_suggestion(question: str, top_k: int = 5) -> Dict[str, Any]:
    """
    完整流程：檢索 → 信心評估 → Prompt 建構 → 生成 → 組裝回傳

    Args:
        question: 使用者問題
        top_k: 檢索前 k 筆

    Returns:
        {
            "suggestion": str,
            "confidence": "high" | "medium" | "low",
            "confidence_reason": str,
            "sources": list[dict],  # {"file_path": str, "chunk_index": int, "preview": str}
        }
    """
    # 1. 檢索
    retrieved_chunks = query_gitlab_context(question, top_k=top_k, use_hybrid=True)

    # 2. 信心評估
    confidence_result = evaluate_confidence(retrieved_chunks)
    confidence_level = confidence_result["level"]
    confidence_reason = confidence_result["reason"]

    # 3. 建構 Prompt
    prompt = build_prompt(question, retrieved_chunks, top_k=top_k)

    # 4. 呼叫生成模型
    try:
        suggestion = call_nim_generate(prompt)
    except RuntimeError as e:
        # 明確回傳錯誤，不靜默失敗
        return {
            "suggestion": f"❌ 生成失敗: {e}",
            "confidence": confidence_level,
            "confidence_reason": confidence_reason,
            "sources": [],
            "error": str(e)
        }

    # 5. 低信心加註提示語
    if confidence_level == "low":
        suggestion = "⚠️ 這個回答在專案內找到的相關內容較少，可能較多是一般性建議，請自行核對\n\n" + suggestion

    # 6. 整理 sources（只列出實際可能被引用的前幾個）
    sources = []
    for i, chunk in enumerate(retrieved_chunks[:top_k], 1):
        sources.append({
            "source_id": i,
            "file_path": chunk.get("file_path", ""),
            "chunk_index": chunk.get("chunk_index", 0),
            "preview": chunk.get("content", "")[:200] + ("..." if len(chunk.get("content", "")) > 200 else ""),
            "rrf_score": chunk.get("rrf_score", 0.0),
            "symbol_hits": chunk.get("symbol_hits", 0),
        })

    return {
        "suggestion": suggestion,
        "confidence": confidence_level,
        "confidence_reason": confidence_reason,
        "sources": sources
    }


if __name__ == "__main__":
    # 測試至少 5 題（含高信心、低信心各至少 1 題）
    # 注意：目前信心評估沒有 low，先測 medium/high
    test_questions = [
        "GPIO 控制怎麼用？",           # high
        "how to set device",           # medium
        "available devices list",      # high
        "建立 whl 安裝包",             # medium
        "推論引擎 裝置設定",           # medium
    ]

    for q in test_questions:
        print(f"\n{'='*60}")
        print(f"查詢: {q}")
        print(f"{'='*60}")
        result = generate_coding_suggestion(q, top_k=5)
        print(f"信心等級: {result['confidence']}")
        print(f"理由: {result['confidence_reason']}")
        print(f"\n建議內容:\n{result['suggestion'][:800]}...")
        print(f"\nSources: {len(result['sources'])} 筆")
        for s in result['sources'][:3]:
            print(f"  [{s['source_id']}] {s['file_path']} chunk#{s['chunk_index']} (rrf={s['rrf_score']:.4f}, sym={s['symbol_hits']})")