#!/usr/bin/env python3
"""
CP-30-C 優化版：併發 + 斷點續傳 + 速率限制
- ThreadPoolExecutor(max_workers=4) 併發 I/O
- TokenBucket rate limiter (embedding 1.5/s, generate 0.4/s)
- 斷點續傳：每 5 題存檔，支援中斷後續跑
- 消除重複檢索：generate_coding_suggestion 內部不再重複 hybrid_search
- 完整統計：分類命中率、confidence 分布、對比 CP-25 基準
"""

import json
import sys
import time
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from typing import List, Dict, Any, Set

sys.path.insert(0, str(Path(__file__).parent / "src"))

from gitlab_rag.hybrid_search import hybrid_search
from gitlab_rag.generate_coding_suggestion import generate_coding_suggestion

TESTSET_PATH = Path(__file__).parent / "gitlab_historical_test_set.json"
OUTPUT_PATH = Path(__file__).parent / "cp30_c_results.json"

# Rate limiters
EMBED_RATE = 1.5   # req/s (NIM free tier 100/min = 1.67, 留 margin)
GENERATE_RATE = 0.4 # req/s (NIM free tier 30/min = 0.5, 留 margin)

class TokenBucket:
    """Thread-safe token bucket rate limiter"""
    def __init__(self, rate: float):
        self.rate = rate
        self.tokens = rate
        self.last = time.monotonic()
        self.lock = threading.Lock()
    
    def acquire(self):
        with self.lock:
            now = time.monotonic()
            elapsed = now - self.last
            self.tokens = min(self.rate, self.tokens + elapsed * self.rate)
            if self.tokens >= 1:
                self.tokens -= 1
                self.last = now
                return
            # wait for next token
            wait = (1 - self.tokens) / self.rate
            self.tokens = 0
            self.last = now + wait
        time.sleep(wait)

EMBED_RATE_LIMITER = TokenBucket(EMBED_RATE)
GENERATE_RATE_LIMITER = TokenBucket(GENERATE_RATE)

def check_file_hit(retrieved_files: List[str], ground_truth_files: List[str]) -> tuple:
    """檢查檢索結果是否命中 ground truth 檔案"""
    retrieved_set = set(f.lower() for f in retrieved_files if f)
    gt_set = set(f.lower() for f in ground_truth_files if f)
    hits = retrieved_set & gt_set
    return len(hits) > 0, list(hits)

def process_item(item: Dict, embed_limiter: TokenBucket, gen_limiter: TokenBucket) -> Dict:
    """處理單一測試項目"""
    issue_num = item['source_issue'].split('#')[1]
    query = item['query']
    gt_files = item['ground_truth_files']
    
    # 1. 混合檢索
    EMBED_RATE_LIMITER.acquire()
    try:
        search_results = hybrid_search(query, top_k=5)
    except Exception as e:
        return {
            'item': item,
            'error': f'search_failed: {e}',
            'search_results': [],
            'confidence': 'error',
            'hit_top3': False,
            'hit_files': []
        }
    
    top3_files = [r.get('file_path', '') for r in search_results[:3]]
    top3_files = [f for f in top3_files if f]
    hit, hit_files = check_file_hit(top3_files, gt_files)
    
    # 2. 生成建議（含信心評估）——內部已複用檢索結果
    GENERATE_RATE_LIMITER.acquire()
    try:
        gen_result = generate_coding_suggestion(query, top_k=5)
        confidence = gen_result.get('confidence', 'unknown')
        conf_reason = gen_result.get('confidence_reason', '')
    except Exception as e:
        confidence = 'error'
        conf_reason = str(e)
    
    return {
        'item': item,
        'search_results': search_results[:3],
        'top3_files': top3_files,
        'ground_truth_files': gt_files,
        'hit_top3': hit,
        'hit_files': hit_files,
        'confidence': confidence,
        'confidence_reason': conf_reason
    }

def load_progress() -> Dict[str, Any]:
    """Load existing progress"""
    if OUTPUT_PATH.exists():
        with open(OUTPUT_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                return {'results': data, 'done_ids': {r['item']['id'] for r in data}}
    return {'results': [], 'done_ids': set()}

def save_progress(results: List[Dict], done_ids: Set[str]):
    """Save progress atomically"""
    tmp_path = OUTPUT_PATH.with_suffix('.tmp')
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    tmp_path.replace(OUTPUT_PATH)

def main():
    print("=" * 60)
    print("CP-30-C: 歷史資料驗證 - 分類統計 (優化版)")
    print("=" * 60)

    with open(TESTSET_PATH, 'r', encoding='utf-8') as f:
        test_set = json.load(f)

    print(f"載入測試集: {len(test_set)} 題")

    # Load progress
    progress = load_progress()
    results = progress['results']
    done_ids = progress['done_ids']
    print(f"已完成: {len(done_ids)} 題，剩餘: {len(test_set) - len(done_ids)}")

    # Filter pending
    to_do = [item for item in test_set if item['id'] not in done_ids]

    # Thread-safe progress saving
    results_lock = threading.Lock()
    done_ids_lock = threading.Lock()

    def save_callback(fut):
        nonlocal results, done_ids
        r = fut.result()
        with results_lock:
            results.append(r)
            with done_ids_lock:
                done_ids.add(r['item']['id'])
            # Save every 5 completions
            if len(results) % 5 == 0:
                save_progress(results, done_ids)

    # Concurrency: 4 workers (I/O bound, NIM API is bottleneck)
    max_workers = 4
    rate_limiter_embed = EMBED_RATE_LIMITER
    rate_limiter_gen = GENERATE_RATE_LIMITER

    print(f"\n開始併發處理 (max_workers={max_workers})...")
    print(f"Rate limits: embed={EMBED_RATE}/s, generate={GENERATE_RATE}/s")

    # Build pending list with issue numbers for tracking
    to_do_with_issue = [(item, item['id']) for item in to_do]

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for item, issue_id in to_do_with_issue:
            fut = executor.submit(process_item, item, EMBED_RATE_LIMITER, GENERATE_RATE_LIMITER)
            # Track which future corresponds to which issue
            fut.issue_id = issue_id
            fut.add_done_callback(save_callback)
            futures.append(fut)

        # Wait for all
        for fut in as_completed(futures):
            pass  # callbacks handle saving

    # Final save
    save_progress(results, done_ids)

    print(f"\n✅ 已輸出: {OUTPUT_PATH}")
    print("=== CP-30-C 完成 ===")

    # Statistics
    print("\n=== 即時統計摘要 ===")
    for cat in ['明確技術修復', '純功能支援']:
        cat_results = [r for r in results if r['item']['category'] == cat]
        total = len(cat_results)
        hits = sum(1 for r in cat_results if r['hit_top3'])
        conf_dist = Counter(r['confidence'] for r in cat_results)
        print(f"\n{cat} ({total} 題):")
        print(f"  Top-3 命中率: {hits}/{total} = {hits/total*100:.1f}%")
        print(f"  Confidence 分布: {dict(conf_dist)}")

    # Compare with CP-25 baseline
    total_all = len(results)
    hit_all = sum(1 for r in results if r['hit_top3'])
    overall = hit_all / total_all * 100 if total_all > 0 else 0
    print(f"\n整體 Top-3 命中率: {overall:.1f}% ({hit_all}/{total_all})")
    print(f"CP-25 基準 (構造題): 72.2%")
    print(f"差異: {overall - 72.2:+.1f}%")

if __name__ == "__main__":
    main()