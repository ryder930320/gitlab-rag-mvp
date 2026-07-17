import json
import math

query_stats = {
    'GPIO 控制怎麼用？': {'expected': 'high', 'n': 29, 'min': 0.900, 'max': 0.950, 'median': 0.950, 'mad': 0.000, 'std': 0.015, 'cv': 0.016, 'range': 0.050, 'rrf_gap': 0.0005},
    'available devices list': {'expected': 'high', 'n': 24, 'min': 0.950, 'max': 0.980, 'median': 0.950, 'mad': 0.000, 'std': 0.006, 'cv': 0.006, 'range': 0.030, 'rrf_gap': 0.0161},
    '推論引擎 裝置設定': {'expected': 'medium', 'n': 30, 'min': 0.150, 'max': 0.950, 'median': 0.950, 'mad': 0.000, 'std': 0.252, 'cv': 0.302, 'range': 0.800, 'rrf_gap': 0.0090},
    '建立 whl 安裝包': {'expected': 'medium', 'n': 23, 'min': 0.010, 'max': 0.950, 'median': 0.900, 'mad': 0.050, 'std': 0.403, 'cv': 0.582, 'range': 0.940, 'rrf_gap': 0.3144},
    '危險區域': {'expected': 'medium', 'n': 21, 'min': 0.950, 'max': 0.950, 'median': 0.950, 'mad': 0.000, 'std': 0.000, 'cv': 0.000, 'range': 0.000, 'rrf_gap': 0.0534},
    '專案打包': {'expected': 'medium', 'n': 19, 'min': 0.020, 'max': 0.980, 'median': 0.950, 'mad': 0.000, 'std': 0.215, 'cv': 0.237, 'range': 0.960, 'rrf_gap': 0.0244},
    'how to set device': {'expected': 'medium', 'n': 16, 'min': 0.900, 'max': 0.950, 'median': 0.950, 'mad': 0.000, 'std': 0.026, 'cv': 0.028, 'range': 0.050, 'rrf_gap': 0.0435},
    '專案編譯流程': {'expected': 'medium', 'n': 9, 'min': 0.900, 'max': 0.950, 'median': 0.920, 'mad': 0.020, 'std': 0.023, 'cv': 0.025, 'range': 0.050, 'rrf_gap': -0.4979},
    '資料庫連線池怎麼設定': {'expected': 'low', 'n': 17, 'min': 0.000, 'max': 0.050, 'median': 0.010, 'mad': 0.010, 'std': 0.016, 'cv': 0.893, 'range': 0.050, 'rrf_gap': 0.0274},
    'Kubernetes 部署怎麼做': {'expected': 'low', 'n': 12, 'min': 0.010, 'max': 0.050, 'median': 0.050, 'mad': 0.000, 'std': 0.020, 'cv': 0.537, 'range': 0.040, 'rrf_gap': 0.0308},
    '微服務 架構 設計 原則': {'expected': 'low', 'n': 9, 'min': 0.000, 'max': 0.050, 'median': 0.010, 'mad': 0.000, 'std': 0.019, 'cv': 1.044, 'range': 0.050, 'rrf_gap': 0.0012},
    '雲端 部署 CI CD 流程': {'expected': 'low', 'n': 8, 'min': 0.100, 'max': 0.150, 'median': 0.150, 'mad': 0.000, 'std': 0.018, 'cv': 0.123, 'range': 0.050, 'rrf_gap': 0.0287},
    '演算法 複雜度 時間 空間': {'expected': 'low', 'n': 9, 'min': 0.010, 'max': 0.150, 'median': 0.050, 'mad': 0.040, 'std': 0.049, 'cv': 0.619, 'range': 0.140, 'rrf_gap': 0.0776},
    'aws azure gcp 雲端部署': {'expected': 'low', 'n': 10, 'min': 0.000, 'max': 0.050, 'median': 0.010, 'mad': 0.000, 'std': 0.018, 'cv': 1.149, 'range': 0.050, 'rrf_gap': 0.0175},
    'machine learning pytorch': {'expected': 'low', 'n': 3, 'min': 0.100, 'max': 0.400, 'median': 0.150, 'mad': 0.050, 'std': 0.161, 'cv': 0.742, 'range': 0.300, 'rrf_gap': -0.0306},
    'docker 容器 編排': {'expected': 'low', 'n': 9, 'min': 0.010, 'max': 0.100, 'median': 0.050, 'mad': 0.000, 'std': 0.030, 'cv': 0.570, 'range': 0.090, 'rrf_gap': -0.0795},
    'react vue angular 前端': {'expected': 'low', 'n': 7, 'min': 0.000, 'max': 0.010, 'median': 0.010, 'mad': 0.000, 'std': 0.004, 'cv': 0.441, 'range': 0.010, 'rrf_gap': 0.0088},
    '專案 設定 怎麼 測試 未知': {'expected': 'low', 'n': 5, 'min': 0.900, 'max': 0.900, 'median': 0.900, 'mad': 0.000, 'std': 0.000, 'cv': 0.000, 'range': 0.000, 'rrf_gap': 0.0258},
}

weights = {q: 1.0 / math.log(1 + s['n']) for q, s in query_stats.items()}

# v3: reranker for both low and high
def predict_v3(query, low_thresh, high_thresh, low_gap_thresh, mad_thresh):
    s = query_stats[query]
    median = s['median']
    mad = s['mad']
    rrf_gap = max(0, s['rrf_gap'])
    
    if median < low_thresh and mad < mad_thresh and rrf_gap < low_gap_thresh:
        return 'low'
    elif median > high_thresh and mad < mad_thresh:
        return 'high'
    else:
        return 'medium'

# v4: RRF gap for high/medium, reranker for low
def predict_v4(query, low_thresh, high_gap, low_gap_thresh, mad_thresh):
    s = query_stats[query]
    median = s['median']
    mad = s['mad']
    rrf_gap = max(0, s['rrf_gap'])
    
    if median < low_thresh and mad < mad_thresh and rrf_gap < low_gap_thresh:
        return 'low'
    elif rrf_gap > high_gap:
        return 'high'
    else:
        return 'medium'

low_range = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30]
high_range = [0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]
low_gap_range = [0.01, 0.02, 0.03, 0.05, 0.08, 0.10, 0.15]
mad_range = [0.01, 0.02, 0.03, 0.05, 0.08, 0.10, 0.15]
high_gap_range = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30]

best = {'acc': 0, 'params': None, 'errors': []}

for lt in low_range:
    for ht in high_range:
        for lgt in low_gap_range:
            for mt in mad_range:
                if lt >= ht:
                    continue
                correct = 0
                errors = []
                for q, s in query_stats.items():
                    pred = predict_v3(q, lt, ht, lgt, mt)
                    exp = s['expected']
                    if pred == exp:
                        correct += 1
                    else:
                        errors.append((q, pred, exp, s['median'], s['rrf_gap'], s['mad']))
                acc = correct / len(query_stats)
                if acc > best['acc']:
                    best = {'acc': acc, 'params': ('v3', lt, ht, lgt, mt), 'errors': errors}

print(f'Best v3 (reranker for both): {best["params"]} acc={best["acc"]:.2f}')
lt, ht, lgt, mt = best['params'][1:]
print(f'  LOW={lt}, HIGH={ht}, LOW_GAP={lgt}, MAD={mt}')
print('Errors:')
for q, pred, exp, med, gap, mad in best['errors']:
    print(f'  {q[:40]:40s} pred={pred:6s} exp={exp:6s} median={med:.3f} gap={gap:.4f} mad={mad:.3f}')

# v4: RRF gap for high/medium, reranker for low
best4 = {'acc': 0, 'params': None, 'errors': []}
for lt in low_range:
    for hg in high_gap_range:
        for lgt in low_gap_range:
            for mt in mad_range:
                if lt >= 0.5:
                    continue
                correct = 0
                errors = []
                for q, s in query_stats.items():
                    pred = predict_v4(q, lt, hg, lgt, mt)
                    exp = s['expected']
                    if pred == exp:
                        correct += 1
                    else:
                        errors.append((q, pred, exp, s['median'], s['rrf_gap'], s['mad']))
                acc = correct / len(query_stats)
                if acc > best4['acc']:
                    best4 = {'acc': acc, 'params': ('v4', lt, hg, lgt, mt), 'errors': errors}

print(f'\nBest v4 (RRF gap for high, reranker for low): {best4["params"]} acc={best4["acc"]:.2f}')
lt, hg, lgt, mt = best4['params'][1:]
print(f'  LOW={lt}, HIGH_GAP={hg}, LOW_GAP={lgt}, MAD={mt}')
print('Errors:')
for q, pred, exp, med, gap, mad in best4['errors']:
    print(f'  {q[:40]:40s} pred={pred:6s} exp={exp:6s} median={med:.3f} gap={gap:.4f} mad={mad:.3f}')