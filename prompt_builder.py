"""Prompt 模板建構器 (CP-16)"""
import os
from typing import List, Dict

# 可依 NIM 模型 context window 調整，預設 4000 字元
DEFAULT_MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "4000"))
DEFAULT_TOP_K = 5


def build_prompt(question: str, retrieved_chunks: List[Dict], max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS, top_k: int = DEFAULT_TOP_K) -> str:
    """
    將檢索到的 chunk 組成送給生成模型的 prompt。

    Args:
        question: 使用者原始問題
        retrieved_chunks: hybrid_search 回傳的結果列表（已按 RRF 分數排序）
        max_context_chars: 注入 context 的字元上限，預設 4000
        top_k: 最多取用前 k 個 chunk，預設 5

    Returns:
        完整的 prompt 字串
    """
    # 取前 top_k，並依 RRF 排名截斷超長內容
    chunks = retrieved_chunks[:top_k]

    # 組裝 context 區塊，超過字元上限則依排名砍掉尾端
    context_blocks = []
    total_chars = 0
    for i, chunk in enumerate(chunks, 1):
        block = f"[來源 {i}] 檔案: {chunk.get('file_path', 'unknown')} (chunk #{chunk.get('chunk_index', 0)})\n{chunk.get('content', '')}"
        if total_chars + len(block) > max_context_chars:
            # 空間不足時，截斷當前 chunk 內容
            remaining = max_context_chars - total_chars
            if remaining > 100:  # 至少保留 100 字元才加入
                block = block[:remaining] + "...[截斷]"
                context_blocks.append(block)
            break
        context_blocks.append(block)
        total_chars += len(block)

    context_str = "\n\n---\n\n".join(context_blocks) if context_blocks else "(無檢索結果)"

    prompt = f"""你是一個專業的程式碼助手，專門協助開發者理解與使用 GitLab 專案內的程式碼。

## 使用者問題
{question}

## 專案內容片段（依檢索相關性排序）
{context_str}

## 回答指示
1. **只根據上述提供的專案內容回答**。若上下文不足以回答，請在回答中誠實說明：「這部分不是根據 repo 內容，是一般性建議」。
2. **不可捏造**專案中不存在的函式、類別、檔案路徑或參數。
3. 回答時**明確引用來源**（如：根據 [來源 1] 的 `infer_base.py` 中的 `Core` 類別...）。
4. 若問題涉及程式碼實作，優先提供具體的函式名稱、參數、呼叫範例。
5. 若上下文資訊不足，清楚說明缺少哪部分資訊，並給出通用建議方向。

請開始回答："""
    return prompt


if __name__ == "__main__":
    # 簡單測試
    from hybrid_search import hybrid_search

    test_questions = [
        "如何建立 whl 安裝包？",
        "GPIO 控制怎麼用？",
        "推論引擎 裝置設定",
    ]

    for q in test_questions:
        print(f"\n{'='*60}")
        print(f"測試查詢: {q}")
        print(f"{'='*60}")
        results = hybrid_search(q, top_k=5)
        prompt = build_prompt(q, results)
        print(prompt[:2000])
        print("... (truncated)")