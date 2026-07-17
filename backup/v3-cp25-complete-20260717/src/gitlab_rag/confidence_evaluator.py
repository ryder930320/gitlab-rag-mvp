"""輕量信心評估 (CP-17 CRAG-lite + CP-24 Reranker + CP-25 不確定性區間)

不訓練額外模型，用現有 RRF/Rerank 分數做簡單信心判斷。
回傳：{
    "level": "high" | "medium" | "low",
    "reason": str,
    "rerank_median": float,
    "rerank_mad": float,
    "rrf_gap": float,
    "symbol_hits": int,
    "vec_rank": int,
    "bm25_rank": int,
    "uncertainty_flags": List[str]
}

判斷邏輯（CP-25 校準後）：
  - Top-1 reranker median < 0.15 且 MAD < 0.05 → low
  - Top-1 reranker median > 0.85 且 MAD < 0.05 且有檢索訊號 → high
  - 其他 → medium
  - uncertainty_flags 標記：high_mad、ambiguous_zone、negative_rrf_gap、high_rerank_weak_retrieval
"""
from typing import List, Dict, Any
from .low_confidence_threshold import evaluate_confidence_with_uncertainty, ConfidenceResult


def _get_primary_score(chunk: Dict[str, Any]) -> float:
    """取得主要排序分數：優先用 rerank_score，回退到 rrf_score"""
    if "rerank_score" in chunk and chunk["rerank_score"] is not None:
        return chunk["rerank_score"]
    return chunk.get("rrf_score", 0.0)


def evaluate_confidence(retrieved_chunks: List[Dict[str, Any]], query: str = None) -> Dict[str, Any]:
    """
    評估檢索結果的信心等級 (CP-25 版本：帶不確定性區間)。

    Args:
        retrieved_chunks: hybrid_search 回傳的結果列表（已按主要分數排序）
        query: 原始查詢字串（用於 reranker 多次重跑計算 MAD，預設 n_runs=1）

    Returns:
        {
            "level": "high" | "medium" | "low",
            "reason": str,
            "rerank_median": float,
            "rerank_mad": float,
            "rrf_gap": float,
            "symbol_hits": int,
            "vec_rank": int,
            "bm25_rank": int,
            "uncertainty_flags": List[str]
        }
    """
    # 使用新的不確定性感知評估器
    result = evaluate_confidence_with_uncertainty(retrieved_chunks, query, n_rerank_runs=1)
    
    # 回傳字典格式（保持向後相容）
    return {
        "level": result.level,
        "reason": result.reason,
        "rerank_median": result.rerank_median,
        "rerank_mad": result.rerank_mad,
        "rrf_gap": result.rrf_gap,
        "symbol_hits": result.symbol_hits,
        "vec_rank": result.vec_rank,
        "bm25_rank": result.bm25_rank,
        "uncertainty_flags": result.uncertainty_flags
    }


# 向後相容：舊版邏輯保留供參考/回退
def evaluate_confidence_legacy(retrieved_chunks: List[Dict[str, Any]]) -> Dict[str, str]:
    """原 CP-17/CP-24 邏輯（僅供回退/比較用）"""
    if not retrieved_chunks:
        return {"level": "low", "reason": "無檢索結果"}

    top1 = retrieved_chunks[0]
    score_1 = _get_primary_score(top1)
    symbol_hits_1 = top1.get("symbol_hits", 0)
    vec_rank_1 = top1.get("vec_rank", 999)
    bm25_rank_1 = top1.get("bm25_rank", 999)

    if len(retrieved_chunks) < 2:
        return {
            "level": "high",
            "reason": "僅有一筆檢索結果，無競爭候選"
        }

    top2 = retrieved_chunks[1]
    score_2 = _get_primary_score(top2)

    if score_1 > 0:
        gap_ratio = (score_1 - score_2) / score_1
    else:
        gap_ratio = 0.0

    if gap_ratio > 0.20:
        return {
            "level": "high",
            "reason": f"Top-1 分數 ({score_1:.4f}) 明顯領先 Top-2 ({score_2:.4f})，差距 {gap_ratio:.1%}"
        }

    if symbol_hits_1 == 0 and vec_rank_1 > 5 and bm25_rank_1 > 8:
        return {
            "level": "low",
            "reason": f"Top-1 無符號命中 (symbol_hits=0)，向量排名 {vec_rank_1}，BM25 排名 {bm25_rank_1}，缺乏強訊號支持"
        }

    reasons = []
    if gap_ratio <= 0.20 and score_1 > 0:
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
    from .hybrid_search import hybrid_search

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
        conf = evaluate_confidence(results, q)
        print(f"信心等級: {conf['level']}")
        print(f"理由: {conf['reason']}")
        print(f"Rerank: median={conf['rerank_median']:.3f}, MAD={conf['rerank_mad']:.3f}")
        print(f"RRF gap: {conf['rrf_gap']:.4f}")
        print(f"Uncertainty flags: {conf['uncertainty_flags']}")
        print(f"Top-1: rrf={results[0]['rrf_score']:.4f} rerank={results[0].get('rerank_score', 0):.3f} vec_rank={results[0].get('vec_rank')} bm25_rank={results[0].get('bm25_rank')} symbol_hits={results[0].get('symbol_hits')} file={results[0]['file_path']}")
        if len(results) > 1:
            print(f"Top-2: rrf={results[1]['rrf_score']:.4f} rerank={results[1].get('rerank_score', 0):.3f} vec_rank={results[1].get('vec_rank')} bm25_rank={results[1].get('bm25_rank')} symbol_hits={results[1].get('symbol_hits')} file={results[1]['file_path']}")