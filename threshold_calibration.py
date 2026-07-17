import math

query_stats = {
    'GPIO 控制怎麼用？': {'expected': 'high', 'n': 29, 'min': 0.900, 'max': 0.950, 'median': 0.950, 'mad': 0.000, 'std': 0.015, 'cv': 0.016, 'range': 0.050, 'rrf_gap': 0.0005, 'symbol_hits': 0, 'vec_rank': 2, 'bm25_rank': 5},
    'available devices list': {'expected': 'high', 'n': 24, 'min': 0.950, 'max': 0.980, 'median': 0.950, 'mad': 0.000, 'std': 0.006, 'cv': 0.006, 'range': 0.030, 'rrf_gap': 0.0161, 'symbol_hits': 0, 'vec_rank': 1, 'bm25_rank': 1},
    '推論引擎 裝置設定': {'expected': 'medium', 'n': 30, 'min': 0.150, 'max': 0.950, 'median': 0.950, 'mad': 0.000, 'std': 0.252, 'cv': 0.302, 'range': 0.800, 'rrf_gap': 0.0090, 'symbol_hits': 1, 'vec_rank': 12, 'bm25_rank': 9},
    '建立 whl 安裝包': {'expected': 'medium', 'n': 23, 'min': 0.010, 'max': 0.950, 'median': 0.900, 'mad': 0.050, 'std': 0.403, 'cv': 0.582, 'range': 0.940, 'rrf_gap': 0.3144, 'symbol_hits': 1, 'vec_rank': 12, 'bm25_rank': 1},
    '危險區域': {'expected': 'medium', 'n': 21, 'min': 0.950, 'max': 0.950, 'median': 0.950, 'mad': 0.000, 'std': 0.000, 'cv': 0.000, 'range': 0.000, 'rrf_gap': 0.0534, 'symbol_hits': 0, 'vec_rank': 1, 'bm25_rank': 4},
    '專案打包': {'expected': 'medium', 'n': 19, 'min': 0.020, 'max': 0.980, 'median': 0.950, 'mad': 0.000, 'std': 0.215, 'cv': 0.237, 'range': 0.960, 'rrf_gap': 0.0244, 'symbol_hits': 0, 'vec_rank': 6, 'bm25_rank': 1},
    'how to set device': {'expected': 'medium', 'n': 16, 'min': 0.900, 'max': 0.950, 'median': 0.950, 'mad': 0.000, 'std': 0.026, 'cv': 0.028, 'range': 0.050, 'rrf_gap': 0.0435, 'symbol_hits': 2, 'vec_rank': 2, 'bm25_rank': 2},
    '專案編譯流程': {'expected': 'medium', 'n': 9, 'min': 0.900, 'max': 0.950, 'median': 0.920, 'mad': 0.020, 'std': 0.023, 'cv': 0.025, 'range': 0.050, 'rrf_gap': -0.4979, 'symbol_hits': 0, 'vec_rank': 6, 'bm25_rank': 3},
    '資料庫連線池怎麼設定': {'expected': 'low', 'n': 17, 'min': 0.000, 'max': 0.050, 'median': 0.010, 'mad': 0.010, 'std': 0.016, 'cv': 0.893, 'range': 0.050, 'rrf_gap': 0.0274, 'symbol_hits': 0, 'vec_rank': 11, 'bm25_rank': 1},
    'Kubernetes 部署怎麼做': {'expected': 'low', 'n': 12, 'min': 0.010, 'max': 0.050, 'median': 0.050, 'mad': 0.000, 'std': 0.020, 'cv': 0.537, 'range': 0.040, 'rrf_gap': 0.0308, 'symbol_hits': 0, 'vec_rank': 4, 'bm25_rank': 2},
    '微服務 架構 設計 原則': {'expected': 'low', 'n': 9, 'min': 0.000, 'max': 0.050, 'median': 0.010, 'mad': 0.000, 'std': 0.019, 'cv': 1.044, 'range': 0.050, 'rrf_gap': 0.0012, 'symbol_hits': 0, 'vec_rank': 8, 'bm25_rank': 2},
    '雲端 部署 CI CD 流程': {'expected': 'low', 'n': 8, 'min': 0.100, 'max': 0.150, 'median': 0.150, 'mad': 0.000, 'std': 0.018, 'cv': 0.123, 'range': 0.050, 'rrf_gap': 0.0287, 'symbol_hits': 0, 'vec_rank': 5, 'bm25_rank': 11},
    '演算法 複雜度 時間 空間': {'expected': 'low', 'n': 9, 'min': 0.010, 'max': 0.150, 'median': 0.050, 'mad': 0.040, 'std': 0.049, 'cv': 0.619, 'range': 0.140, 'rrf_gap': 0.0776, 'symbol_hits': 0, 'vec_rank': 3, 'bm25_rank': 1},
    'aws azure gcp 雲端部署': {'expected': 'low', 'n': 10, 'min': 0.000, 'max': 0.050, 'median': 0.010, 'mad': 0.000, 'std': 0.018, 'cv': 1.149, 'range': 0.050, 'rrf_gap': 0.0175, 'symbol_hits': 0, 'vec_rank': 7, 'bm25_rank': 1},
    'machine learning pytorch': {'expected': 'low', 'n': 3, 'min': 0.100, 'max': 0.400, 'median': 0.150, 'mad': 0.050, 'std': 0.161, 'cv': 0.742, 'range': 0.300, 'rrf_gap': -0.0306, 'symbol_hits': 0, 'vec_rank': 2, 'bm25_rank': 8},
    'docker 容器 編排': {'expected': 'low', 'n': 9, 'min': 0.010, 'max': 0.100, 'median': 0.050, 'mad': 0.000, 'std': 0.030, 'cv': 0.570, 'range': 0.090, 'rrf_gap': -0.0795, 'symbol_hits': 0, 'vec_rank': 9, 'bm25_rank': 6},
    'react vue angular 前端': {'expected': 'low', 'n': 7, 'min': 0.000, 'max': 0.010, 'median': 0.010, 'mad': 0.000, 'std': 0.004, 'cv': 0.441, 'range': 0.010, 'rrf_gap': 0.0088, 'symbol_hits': 0, 'vec_rank': 5, 'bm25_rank': 1},
    '專案 設定 怎麼 測試 未知': {'expected': 'low', 'n': 5, 'min': 0.900, 'max': 0.900, 'median': 0.900, 'mad': 0.000, 'std': 0.000, 'cv': 0.000, 'range': 0.000, 'rrf_gap': 0.0258, 'symbol_hits': 0, 'vec_rank': 9, 'bm25_rank': 1},
}

def predict_final(query, stats):
    s = stats[query]
    median = s['median']
    mad = s['mad']
    rrf_gap = max(0, s['rrf_gap'])
    symbol_hits = s.get('symbol_hits', 0)
    vec_rank = s.get('vec_rank', 999)
    bm25_rank = s.get('bm25_rank', 999)
    
    # Low: confidently low reranker
    if median < 0.15 and mad < 0.05:
        return 'low'
    
    # High: confidently high reranker + some retrieval signal
    if median > 0.85:
        has_signal = rrf_gap > 0.15 or symbol_hits > 0 or vec_rank <= 2 or bm25_rank <= 2
        if has_signal:
            return 'high'
        else:
            return 'medium'
    
    return 'medium'

print('=== Final Practical Thresholds ===')
correct = 0
errors = []
for q, s in query_stats.items():
    pred = predict_final(q, query_stats)
    exp = s['expected']
    if pred == exp:
        correct += 1
    else:
        errors.append((q, pred, exp, s['median'], s['mad'], s['rrf_gap'], s.get('symbol_hits', 0), s.get('vec_rank', 999), s.get('bm25_rank', 999)))

print(f'Accuracy: {correct}/{len(query_stats)} = {correct/len(query_stats):.1%}')
print()
print('Errors (reranker vs expected):')
for q, pred, exp, med, mad, gap, sym, vr, br in errors:
    print(f'  {q[:40]:40s} pred={pred:6s} exp={exp:6s} median={med:.3f} mad={mad:.3f} gap={gap:.4f} sym={sym} vr={vr} br={br}')

print()
print('Thresholds chosen:')
print('  LOW_THRESH = 0.15 (reranker median)')
print('  HIGH_THRESH = 0.85 (reranker median)')
print('  HIGH requires: median>0.85 AND (rrf_gap>0.15 OR symbol_hits>0 OR vec_rank<=2 OR bm25_rank<=2)')
print('  MAD_THRESH = 0.05 (uncertainty flag)')
print()
print('Uncertainty flags:')
print('  - mad > 0.05 -> uncertain')
print('  - median in [0.15, 0.85) -> uncertain')
print('  - high reranker but no retrieval signal -> uncertain')
print('  - cp22_010 "專案 設定 怎麼 測試 未知" -> low label is controversial, reranker says 0.9')