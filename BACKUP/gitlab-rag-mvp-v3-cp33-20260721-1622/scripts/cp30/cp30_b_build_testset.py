#!/usr/bin/env python3
"""
CP-30-B: 組建「真實問題 + Ground Truth」資料集
讀取 cp30_a_inventory.json，產出 gitlab_historical_test_set.json
格式對齊 golden_test_set.json，包含 category 欄位區分「明確技術修復」vs「純功能支援」
"""

import os
import json
import re
from pathlib import Path

INVENTORY_PATH = Path(__file__).parent / "cp30_a_inventory.json"
OUTPUT_PATH = Path(__file__).parent / "gitlab_historical_test_set.json"

def load_inventory():
    with open(INVENTORY_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

def extract_query_from_commits(main_commit, impl_commits):
    """從 commit message 提煉自然語言問題"""
    parts = []
    if main_commit:
        title = main_commit.get('title', '')
        # 移除 "Issue #XXXXX:" 前綴
        title = re.sub(r'^Issue\s*#\d+\s*:\s*', '', title, flags=re.IGNORECASE)
        if title:
            parts.append(title)
    
    # 從實作 commits 提取關鍵動作
    for ic in impl_commits:
        t = ic.get('title', '')
        if t and 'Add ' not in t and 'Update ' not in t and 'Modify ' not in t:
            parts.append(t)
    
    # 如果沒有足夠內容，用主 commit 的完整 message
    if not parts and main_commit:
        msg = main_commit.get('message', '').strip()
        if msg:
            parts.append(msg.split('\n')[0])
    
    return '；'.join(parts) if parts else (main_commit.get('title', '') if main_commit else 'Unknown issue')

def get_ground_truth_diff(issue_number, project_id="153"):
    """實際去抓取該 issue 群組所有 commits 的完整 diff"""
    # 這裡先返回檔案清單，CP-30-C 時再按需抓取完整 diff
    return f"See commit diffs for Issue #{issue_number} in project {project_id}"

def build_test_set(inventory):
    pairs = inventory.get('pairs', [])
    test_set = []
    excluded = []
    
    for p in pairs:
        quality = p.get('quality', 'unclear')
        issue_num = p.get('issue_number', '')
        
        # 決定 category
        if quality == 'clear_technical_fix':
            category = '明確技術修復'
        elif quality == 'feature_support':
            category = '純功能支援'
        elif quality == 'feature_with_fix':
            category = '功能支援含修復'
        elif quality == 'maintenance':
            category = '一般維護'
        else:
            category = '不明確'
        
        main_commit = p.get('main_commit', {})
        impl_commits = p.get('impl_commits', [])
        all_files = p.get('all_changed_files', [])
        
        # 構建 query
        query = extract_query_from_commits(main_commit, impl_commits)
        
        # 收集所有 commit hashes
        commit_hashes = []
        if main_commit and main_commit.get('hash'):
            commit_hashes.append(main_commit['hash'])
        for ic in impl_commits:
            if ic.get('hash'):
                commit_hashes.append(ic['hash'])
        
        # 標記品質
        label_quality = 'high' if quality in ('clear_technical_fix', 'feature_with_fix') else 'medium'
        
        # 決定是否納入測試集（排除 noise、unclear、maintenance）
        if quality in ('exclude_noise', 'unclear'):
            excluded.append({
                'issue_number': issue_num,
                'reason': f'品質分類為 {quality}',
                'quality': quality,
                'main_commit_title': main_commit.get('title', '') if main_commit else ''
            })
            continue
        
        if quality == 'maintenance':
            # 維護類也可選納入，標記為 low quality
            label_quality = 'low'
        
        item = {
            'id': f"gitlab_historical_{issue_num}",
            'query': query,
            'ground_truth_files': all_files,
            'ground_truth_diff': get_ground_truth_diff(issue_num),
            'origin': 'gitlab_historical',
            'category': category,
            'source_issue': f"Issue #{issue_num}",
            'source_commits': commit_hashes,
            'main_commit': main_commit.get('hash') if main_commit else None,
            'commit_count': p.get('commit_count', 0),
            'label_quality': label_quality,
            'notes': f"Project 153 (aaeonFramework), {category}, {p.get('commit_count', 0)} commits"
        }
        test_set.append(item)
    
    return test_set, excluded

def main():
    print("=" * 60)
    print("CP-30-B: 組建 GitLab 歷史資料驗證集")
    print("=" * 60)
    
    inventory = load_inventory()
    print(f"載入盤點資料：{inventory['valuable_pairs_count']} 組有效配對")
    
    test_set, excluded = build_test_set(inventory)
    
    # 統計
    cat_counts = {}
    for item in test_set:
        cat = item['category']
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
    
    print(f"\n【納入測試集】{len(test_set)} 題")
    for cat, cnt in sorted(cat_counts.items()):
        print(f"  {cat}: {cnt}")
    
    print(f"\n【排除清單】{len(excluded)} 題")
    for ex in excluded:
        print(f"  Issue #{ex['issue_number']}: {ex['reason']} (主 commit: {ex['main_commit_title'][:60]})")
    
    # 輸出 JSON
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(test_set, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 已輸出: {OUTPUT_PATH}")
    print(f"   格式對齊 golden_test_set.json，含 category、origin、source_commits 等欄位")
    print("\n=== CP-30-B 完成，等待確認後進入 CP-30-C ===")

if __name__ == "__main__":
    main()