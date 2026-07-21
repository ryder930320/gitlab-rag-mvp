#!/usr/bin/env python3
"""
CP-30-C: 拿 gitlab_historical_test_set.json 跑現有系統，分類統計
- 分別統計「明確技術修復」vs「純功能支援」的 Top-3 命中率、confidence 分布
- 輸出完整原始結果供後續分析
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from gitlab_rag.hybrid_search import hybrid_search
from gitlab_rag.generate_coding_suggestion import generate_coding_suggestion

TESTSET_PATH = Path(__file__).parent / "gitlab_historical_test_set.json"
OUTPUT_PATH = Path(__file__).parent / "cp30_c_results.json"

def check_file_hit(retrieved_files, ground_truth_files):
    """檢查檢索結果是否命中 ground truth 檔案"""
    retrieved_set = set(f.lower() for f in retrieved_files)
    gt_set = set(f.lower() for f in ground_truth_files)
    hits = retrieved_set & gt_set
    return len(hits) > 0, list(hits)

def main():
    print("=" * 60)
    print("CP-30-C: 歷史資料驗證 - 分類統計")
    print("=" * 60)
    
    with open(TESTSET_PATH, 'r', encoding='utf-8') as f:
        test_set = json.load(f)
    
    print(f"載入測試集: {len(test_set)} 題")
    
    # 分組
    by_category = {}
    for item in test_set:
        cat = item['category']
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(item)
    
    for cat, items in by_category.items():
        print(f"  {cat}: {len(items)} 題")
    
    results = []
    
    for cat, items in by_category.items():
        print(f"\n{'='*60}")
        print(f"處理類別: {cat} ({len(items)} 題)")
        print(f"{'='*60}")
        
        for idx, item in enumerate(items, 1):
            issue_num = item['source_issue'].split('#')[1]
            query = item['query']
            gt_files = item['ground_truth_files']
            
            print(f"\n[{idx}/{len(items)}] Issue #{issue_num} | {cat}")
            print(f"  Query: {query[:80]}...")
            print(f"  GT Files: {gt_files[:3]}")
            
            # 1. 混合檢索
            try:
                search_results = hybrid_search(query, top_k=5)
            except Exception as e:
                print(f"  ❌ 檢索失敗: {e}")
                results.append({
                    'item': item,
                    'error': f'search_failed: {e}',
                    'search_results': [],
                    'confidence': 'error',
                    'hit_top3': False,
                    'hit_files': []
                })
                time.sleep(1)  # 避免 rate limit
                continue
            
            # 提取前 3 條的檔案路徑
            top3_files = [r.get('file_path', '') for r in search_results[:3]]
            top3_files = [f for f in top3_files if f]
            
            # 檢查命中
            hit, hit_files = check_file_hit(top3_files, gt_files)
            
            # 2. 生成建議（含信心評估）
            try:
                gen_result = generate_coding_suggestion(query, top_k=5)
                confidence = gen_result.get('confidence', 'unknown')
                conf_reason = gen_result.get('confidence_reason', '')
            except Exception as e:
                print(f"  ❌ 生成失敗: {e}")
                confidence = 'error'
                conf_reason = str(e)
            
            print(f"  Top-3 Files: {top3_files}")
            print(f"  Hit: {'✅' if hit else '❌'} {hit_files if hit else ''}")
            print(f"  Confidence: {confidence}")
            
            results.append({
                'item': item,
                'search_results': search_results[:3],
                'top3_files': top3_files,
                'ground_truth_files': gt_files,
                'hit_top3': hit,
                'hit_files': hit_files,
                'confidence': confidence,
                'confidence_reason': conf_reason,
                'suggestion_preview': gen_result.get('suggestion', '')[:500] if 'gen_result' in locals() else ''
            })
            
            # 節流避免 NIM 429
            time.sleep(2)
    
    # 統計
    print(f"\n{'='*60}")
    print("CP-30-C 統計結果")
    print(f"{'='*60}")
    
    stats = {}
    for r in results:
        cat = r['item']['category']
        if cat not in stats:
            stats[cat] = {'total': 0, 'hit': 0, 'conf_high': 0, 'conf_medium': 0, 'conf_low': 0, 'conf_error': 0}
        stats[cat]['total'] += 1
        if r['hit_top3']:
            stats[cat]['hit'] += 1
        conf = r['confidence']
        if conf == 'high':
            stats[cat]['conf_high'] += 1
        elif conf == 'medium':
            stats[cat]['conf_medium'] += 1
        elif conf == 'low':
            stats[cat]['conf_low'] += 1
        else:
            stats[cat]['conf_error'] += 1
    
    for cat, s in stats.items():
        hit_rate = s['hit'] / s['total'] * 100 if s['total'] > 0 else 0
        print(f"\n{cat} ({s['total']} 題):")
        print(f"  Top-3 命中率: {hit_rate:.1f}% ({s['hit']}/{s['total']})")
        print(f"  Confidence: high={s['conf_high']}, medium={s['conf_medium']}, low={s['conf_low']}, error={s['conf_error']}")
    
    # 對比 CP-25 基準 (72.2% 整體)
    total_all = sum(s['total'] for s in stats.values())
    hit_all = sum(s['hit'] for s in stats.values())
    overall = hit_all / total_all * 100 if total_all > 0 else 0
    print(f"\n整體 Top-3 命中率: {overall:.1f}% ({hit_all}/{total_all})")
    print(f"CP-25 基準 (構造題): 72.2%")
    print(f"差異: {overall - 72.2:+.1f}%")
    
    # 儲存完整結果
    output = {
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'total_questions': len(results),
        'by_category': stats,
        'overall_hit_rate': overall,
        'cp25_baseline': 72.2,
        'difference': overall - 72.2,
        'results': results
    }
    
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"\n✅ 完整結果已輸出: {OUTPUT_PATH}")
    print("=== CP-30-C 完成 ===")

if __name__ == "__main__":
    main()