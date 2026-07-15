"""輕量信心評估 (CP-17 CRAG-lite)

不訓練額外模型，用現有 RRF 分數做簡單信心判斷。
回傳：{"level": "high" | "medium" | "low", "reason": str}

判斷邏輯（起始版本，可依實測結果調整）：
  - Top-1 與 Top-2 的 RRF 分數差距明顯（例如 > 20%）→ high
  - 差距不明顯，代表候選之間排序不夠篤定 → medium
  - Top-1 的 symbol_hits=0 且 bm25_rank 很後面（例如 > 8）且 vector_rank 也不靠前（例如 > 5）→ low
    （向量和關鍵字都沒有強訊號支持這個結果）
"""
from typing import List, Dict, Any


def evaluate_confidence(retrieved_chunks: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    評估檢索結果的信心等級。

    Args:
        retrieved_chunks: hybrid_search 回傳的結果列表（已按 rrf_score 排序）

    Returns:
        {"level": "high" | "medium" | "low", "reason": str}
    """
    if not retrieved_chunks:
        return {"level": "low", "reason": "無檢索結果"}

    top1 = retrieved_chunks[0]

    # 取得關鍵指標
    rrf_score_1 = top1.get("rrf_score", 0.0)
    symbol_hits_1 = top1.get("symbol_hits", 0)
    vec_rank_1 = top1.get("vec_rank", 999)
    bm25_rank_1 = top1.get("bm25_rank", 999)

    # 情況 1：無次優結果 → 視同 high（只有一個強候選）
    if len(retrieved_chunks) < 2:
        return {
            "level": "high",
            "reason": "僅有一筆檢索結果，無競爭候選"
        }

    top2 = retrieved_chunks[1]
    rrf_score_2 = top2.get("rrf_score", 0.0)

    # 計算 Top-1/Top-2 差距比例
    if rrf_score_1 > 0:
        gap_ratio = (rrf_score_1 - rrf_score_2) / rrf_score_1
    else:
        gap_ratio = 0.0

    # 規則 1：Top-1 明顯領先（差距 > 20%）→ high
    if gap_ratio > 0.20:
        return {
            "level": "high",
            "reason": f"Top-1 RRF 分數 ({rrf_score_1:.4f}) 明顯領先 Top-2 ({rrf_score_2:.4f})，差距 {gap_ratio:.1%}"
        }

    # 規則 2：Top-1 沒有符號命中、且向量/BM25 排名都不靠前 → low
    if symbol_hits_1 == 0 and vec_rank_1 > 5 and bm25_rank_1 > 8:
        return {
            "level": "low",
            "reason": f"Top-1 無符號命中 (symbol_hits=0)，向量排名 {vec_rank_1}，BM25 排名 {bm25_rank_1}，缺乏強訊號支持"
        }

    # 規則 3：其他情況 → medium
    reasons = []
    if gap_ratio <= 0.20 and rrf_score_1 > 0:
        reasons.append(f"Top-1/Top-2 差距較小 ({gap_ratio:.1%})，候選間無明顯共識")
    if symbol_hits_1 > 0:
        reasons.append(f"Top-1 有符號命中 ({symbol_hits_1} 個)")
    if vec_rank_1 <= 5:
        reasons.append(f"向量排名靠前 (rank={vec_rank_1})")
    if bm25_rank_1 <= 8:
        reasons.append(f"BM25 排名靠前 (rank={bm25_rank_1})")

    reason_str = "；".join(reasons) if reasons else "綜合訊號中等"
    return {"level": "medium", "reason": reason_str}


if __name__ == "__main__":
    from hybrid_search import hybrid_search

    # 測試題目（CP-15 已知會失準的 + 穩定答對的 + 其他）
    test_questions = [
        ("建立 whl 安裝包", "已知會失準的純中文查詢"),
        ("GPIO 控制怎麼用？", "CP-15 穩定答對的題目"),
        ("推論引擎 裝置設定", "純中文查詢，向量模型挑戰"),
        ("how to set device", "英文查詢，符號匹配應生效"),
        ("available devices list", "英文查詢，已知穩定"),
        ("專案編譯流程", "純中文新題"),
    ]

    for q, note in test_questions:
        print(f"\n{'='*60}")
        print(f"查詢: {q}  ({note})")
        print(f"{'='*60}")
        results = hybrid_search(q, top_k=5)
        conf = evaluate_confidence(results)
        print(f"信心等級: {conf['level']}")
        print(f"理由: {conf['reason']}")
        print(f"Top-1: rrf={results[0]['rrf_score']:.4f} vec_rank={results[0].get('vec_rank')} bm25_rank={results[0].get('bm25_rank')} symbol_hits={results[0].get('symbol_hits')} file={results[0]['file_path']}")
        if len(results) > 1:
            print(f"Top-2: rrf={results[1]['rrf_score']:.4f} vec_rank={results[1].get('vec_rank')} bm25_rank={results[1].get('bm25_rank')} symbol_hits={results[1].get('symbol_hits')} file={results[1]['file_path']}")