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
    retrieved_set = set(f.lower() for f in retrieved_files if f)
    gt_set = set(f.lower() for f in ground_truth_files if f)
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
                time.sleep(1)
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
                'confidence': confidence,
                'confidence_reason': conf_reason,
                'hit_top3': hit,
                'hit_files': hit_files
            })
            
            time.sleep(1)  # 避免 rate limit
    
    # 輸出結果
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 已輸出: {OUTPUT_PATH}")
    print("\n=== CP-30-C 完成 ===")
    
    # 即時統計
    print("\n=== 即時統計摘要 ===")
    for cat in by_category:
        cat_results = [r for r in results if r['item']['category'] == cat]
        total = len(cat_results)
        hits = sum(1 for r in cat_results if r['hit_top3'])
        conf_dist = {}
        for r in cat_results:
            c = r['confidence']
            conf_dist[c] = conf_dist.get(c, 0) + 1
        print(f"\n{cat} ({total} 題):")
        print(f"  Top-3 命中率: {hits}/{total} = {hits/total*100:.1f}%")
        print(f"  Confidence 分布: {conf_dist}")

if __name__ == "__main__":
    main()