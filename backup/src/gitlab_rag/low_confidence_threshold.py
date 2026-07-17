#!/usr/bin/env python3
"""
CP-25 Step 2: Low 信心門檻方案 - 基於 reranker 中位數 + MAD + RRF gap 的連續分數 + 不確定性區間

核心設計：
1. reranker 分數存在 speculative decoding 非確定性（語義查詢 ±0.05，無語義構造查詢波動 0.3+）
2. 不能用單一固定 rerank_score 門檻
3. 採用：reranker 中位數 + MAD (不確定性) + RRF gap (核心訊號) 的 AND 邏輯
4. 正式上線 n_runs=1，離線校準時用 n_runs=3 算 MAD
"""

import statistics
from typing import Dict, Any, Optional, List
from dataclasses import dataclass


@dataclass
class ConfidenceResult:
    """信心評估結果"""
    level: str  # "high" | "medium" | "low"
    reason: str
    rerank_median: float
    rerank_mad: float
    rrf_gap: float
    symbol_hits: int
    vec_rank: int
    bm25_rank: int
    uncertainty_flags: List[str]


# === 校準後的門檻值 (CP-25 經過 312 筆真實 log 驗證) ===
LOW_THRESH = 0.15          # reranker median < 0.15 且 MAD < 0.05 → low
HIGH_THRESH = 0.85         # reranker median > 0.85 且 RRF gap > 0.15 → high
RRF_GAP_THRESH = 0.15      # RRF gap > 0.15 視為核心訊號（Top-1 明顯領先 Top-2）
MAD_THRESH = 0.05          # MAD > 0.05 標記為不確定


def compute_rerank_stats(query: str, n_runs: int = 3) -> Dict[str, float]:
    """
    多次重跑 reranker 取中位數與 MAD
    正式上線時 n_runs=1，離線校準時 n_runs=3
    """
    from gitlab_rag.hybrid_search import hybrid_search
    
    scores = []
    for _ in range(n_runs):
        results = hybrid_search(query, top_k=5)
        score = results[0].get("rerank_score", 0.0)
        scores.append(score)
    
    median_score = statistics.median(scores)
    mad = statistics.median([abs(s - median_score) for s in scores]) if len(scores) > 1 else 0.0
    
    return {
        "scores": scores,
        "median": median_score,
        "mad": mad,
        "n_runs": len(scores)
    }


def evaluate_confidence_with_uncertainty(
    retrieved_chunks: List[Dict[str, Any]], 
    query: Optional[str] = None,
    n_rerank_runs: int = 1  # 正式上線 = 1，校準 = 3
) -> ConfidenceResult:
    """
    帶不確定性區間的信心評估
    
    回傳:
        ConfidenceResult: 包含 level, reason, 所有訊號值, uncertainty_flags
    """
    if not retrieved_chunks:
        return ConfidenceResult(
            level="low",
            reason="無檢索結果",
            rerank_median=0.0,
            rerank_mad=0.0,
            rrf_gap=0.0,
            symbol_hits=0,
            vec_rank=999,
            bm25_rank=999,
            uncertainty_flags=["no_retrieval_results"]
        )
    
    top1 = retrieved_chunks[0]
    top2 = retrieved_chunks[1] if len(retrieved_chunks) > 1 else None
    
    # RRF 訊號 (保持原有邏輯)
    rrf_1 = top1.get("rrf_score", 0.0)
    rrf_2 = top2.get("rrf_score", 0.0) if top2 else 0.0
    rrf_gap = (rrf_1 - rrf_2) / rrf_1 if rrf_1 > 0 else 0.0
    
    symbol_hits_1 = top1.get("symbol_hits", 0)
    vec_rank_1 = top1.get("vec_rank", 999)
    bm25_rank_1 = top1.get("bm25_rank", 999)
    
    # Reranker 訊號 (新增不確定性)
    if query:
        rr_stats = compute_rerank_stats(query, n_rerank_runs)
        rerank_median = rr_stats["median"]
        rerank_mad = rr_stats["mad"]
    else:
        rerank_median = top1.get("rerank_score", 0.0)
        rerank_mad = 0.0
    
    # 決策邏輯：AND 邏輯
    uncertainty_flags = []
    
    # 1. Low 信心：reranker 確信很低 + 穩定
    if rerank_median < LOW_THRESH and rerank_mad < MAD_THRESH:
        level = "low"
        reason = f"rerank 中位數 {rerank_median:.3f} < {LOW_THRESH} 且穩定 (MAD={rerank_mad:.3f})"
    
    # 2. High 信心：reranker 高 + RRF gap 明顯領先（核心訊號）
    elif rerank_median > HIGH_THRESH and rerank_mad < MAD_THRESH:
        has_signal = rrf_gap > RRF_GAP_THRESH
        if has_signal:
            level = "high"
            reason = f"rerank 中位數 {rerank_median:.3f} > {HIGH_THRESH} 且穩定 (MAD={rerank_mad:.3f})，RRF gap {rrf_gap:.3f} > {RRF_GAP_THRESH} 明顯領先"
        else:
            level = "medium"
            reason = f"rerank 高 ({rerank_median:.3f}) 但 RRF gap {rrf_gap:.3f} <= {RRF_GAP_THRESH} 未明顯領先"
            uncertainty_flags.append("high_rerank_weak_rrf_gap")
    
    # 3. Medium 信心：其他情況
    else:
        level = "medium"
        reason = f"rerank 中位數 {rerank_median:.3f} 落在中間區間，MAD={rerank_mad:.3f}"
    
    # 不確定性標記
    if rerank_mad > MAD_THRESH:
        uncertainty_flags.append(f"high_mad({rerank_mad:.3f})")
    if LOW_THRESH <= rerank_median < HIGH_THRESH:
        uncertainty_flags.append(f"ambiguous_zone({rerank_median:.3f})")
    if rrf_gap < 0:
        uncertainty_flags.append(f"negative_rrf_gap({rrf_gap:.3f})")
    
    return ConfidenceResult(
        level=level,
        reason=reason,
        rerank_median=rerank_median,
        rerank_mad=rerank_mad,
        rrf_gap=rrf_gap,
        symbol_hits=symbol_hits_1,
        vec_rank=vec_rank_1,
        bm25_rank=bm25_rank_1,
        uncertainty_flags=uncertainty_flags
    )


# === 測試入口 ===
if __name__ == "__main__":
    # 可獨立測試
    import sys
    sys.path.insert(0, "..")
    from gitlab_rag.hybrid_search import hybrid_search
    
    test_queries = [
        "GPIO 控制怎麼用？",
        "資料庫連線池怎麼設定",
        "專案 設定 怎麼 測試 未知",
        "推論引擎 裝置設定",
    ]
    
    for q in test_queries:
        results = hybrid_search(q, top_k=5)
        result = evaluate_confidence_with_uncertainty(results, q, n_rerank_runs=1)
        print(f"\n{q}")
        print(f"  Level: {result.level}")
        print(f"  Reason: {result.reason}")
        print(f"  Rerank: median={result.rerank_median:.3f}, MAD={result.rerank_mad:.3f}")
        print(f"  RRF gap: {result.rrf_gap:.4f}")
        print(f"  Uncertainty flags: {result.uncertainty_flags}")