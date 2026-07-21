#!/usr/bin/env python3
"""
CP-30-A 完整掃描：掃描全部 603 commits，提取 Issue #、分群、抓 diff、品質分級
輸出：cp30_a_inventory.json
"""

import os
import re
import json
import time
import gitlab
from pathlib import Path
from dotenv import load_dotenv
from collections import defaultdict

load_dotenv()

GITLAB_URL = os.getenv("GITLAB_URL")
GITLAB_TOKEN = os.getenv("GITLAB_TOKEN")
GITLAB_PROJECT = os.getenv("GITLAB_PROJECT")

gl = gitlab.Gitlab(GITLAB_URL, private_token=GITLAB_TOKEN)
project = gl.projects.get(GITLAB_PROJECT)

CACHE_DIR = Path(__file__).parent / "cp30_cache"
CACHE_DIR.mkdir(exist_ok=True)

ISSUE_PATTERN = re.compile(r'Issue\s*#(\d+)', re.IGNORECASE)

def save_json(data, filename):
    with open(CACHE_DIR / filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)

def load_json(filename):
    path = CACHE_DIR / filename
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

def fetch_all_commits():
    """拉取所有 commits（帶快取）"""
    cached = load_json("all_commits.json")
    if cached:
        print(f"  從快取載入 {len(cached)} 筆 commits")
        return cached
    
    print("  拉取所有 commits...")
    commits = []
    for c in project.commits.list(all=True, per_page=100):
        commits.append({
            'id': c.id,
            'short_id': c.short_id,
            'title': c.title,
            'message': c.message,
            'created_at': c.created_at,
            'author_name': c.author_name,
        })
        if len(commits) % 100 == 0:
            print(f"    已獲取 {len(commits)} 筆...")
    
    save_json(commits, "all_commits.json")
    print(f"  完成：共 {len(commits)} 筆 commits")
    return commits

def fetch_commit_diff(commit_id):
    """取得單一 commit 的異動檔案（帶快取）"""
    cache_file = f"diff_{commit_id[:8]}.json"
    cached = load_json(cache_file)
    if cached:
        return cached
    
    try:
        commit = project.commits.get(commit_id)
        diffs = commit.diff(get_all=True)
        files = []
        for d in diffs:
            new_path = d.get('new_path')
            old_path = d.get('old_path')
            path = new_path or old_path
            if path:
                files.append(path)
        files = list(set(files))
        save_json(files, cache_file)
        return files
    except Exception as e:
        return [f"[ERROR: {e}]"]

def classify_commit_quality(title, message, changed_files):
    """判斷 commit 品質"""
    text = f"{title} {message}".lower()
    
    # 排除：merge、版本更新、格式、整理
    exclude_patterns = [
        r'merge branch', r'merge remote', r'update driver version',
        r'update version', r'driver ver', r'version sequence',
        r'delete useless', r'delete space', r'restore commit',
        r'remove .*file', r'fix typo', r'fix space', r'fix build',
        r'update inf version', r'update inf rev', r'modify inf version',
    ]
    for pat in exclude_patterns:
        if re.search(pat, text):
            return 'exclude_noise'
    
    # 明確技術問題修復
    fix_patterns = [
        r'fix.*bsod', r'fix.*issue', r'fix.*bug', r'fix.*error',
        r'solve.*issue', r'resolve.*issue', r'correct.*issue',
        r'bsod', r'blue screen', r'crash', r'hang', r'freeze',
        r'memory leak', r'leak', r'deadlock', r'race condition',
        r'timeout', r'null pointer', r'segfault', r'exception',
        r'smbus.*issue', r'i2c.*issue', r'i2c.*bug', r'smbus.*bug',
        r'backlight.*issue', r'backlight.*fix', r'backlight.*bug',
        r'gpio.*issue', r'gpio.*fix', r'gpio.*bug',
        r'write block', r'read block', r'block data',
        r'unknown', r'unknow', r'incorrect', r'wrong',
        r'corrupt', r'invalid', r'fail', r'error',
    ]
    for pat in fix_patterns:
        if re.search(pat, text):
            return 'clear_technical_fix'
    
    # 新增板卡支援 / 功能開發
    feature_patterns = [
        r'support board', r'add.*inf setting', r'add.*inf settings',
        r'add.*feature', r'new board', r'new platform',
        r'initial', r'initial driver',
    ]
    for pat in feature_patterns:
        if re.search(pat, text):
            return 'feature_support'
    
    # 版本更新 / 一般維護
    maint_patterns = [
        r'update driver', r'update board', r'modify board',
        r'update inf', r'modify inf', r'add.*setting',
        r'remove.*debug', r'disable', r'enable',
    ]
    for pat in maint_patterns:
        if re.search(pat, text):
            return 'maintenance'
    
    return 'unclear'

def main():
    print("=" * 60)
    print("CP-30-A 完整盤點：Project 153 (aaeonFramework)")
    print("=" * 60)
    
    # 1. 取得所有 commits
    commits = fetch_all_commits()
    
    # 2. 提取 Issue # 並分群
    print("\n[2/5] 提取 Issue 編號並分群...")
    issue_groups = defaultdict(list)
    commits_with_issue = 0
    commits_without_issue = 0
    
    for c in commits:
        matches = ISSUE_PATTERN.findall(c['message'])
        if matches:
            commits_with_issue += 1
            for issue_num in set(matches):  # 去重
                issue_groups[issue_num].append(c)
        else:
            commits_without_issue += 1
    
    print(f"  含 Issue # 的 commits: {commits_with_issue}")
    print(f"  無 Issue # 的 commits: {commits_without_issue}")
    print(f"  獨立 Issue 編號數: {len(issue_groups)}")
    
    # 3. 為每個 commit 抓 diff
    print("\n[3/5] 抓取所有 commits 的異動檔案...")
    commit_files_cache = {}
    for i, c in enumerate(commits):
        if i % 50 == 0:
            print(f"  進度: {i}/{len(commits)}")
        files = fetch_commit_diff(c['id'])
        commit_files_cache[c['id']] = files
    
    # 4. 品質分級並建立完整配對資料
    print("\n[4/5] 品質分級與資料整理...")
    
    quality_stats = defaultdict(int)
    pairs = []  # 最終輸出的配對清單
    
    for issue_num, issue_commits in issue_groups.items():
        # 取得所有相關 commits 的檔案
        all_files = set()
        main_commit = None
        impl_commits = []
        
        for c in issue_commits:
            files = commit_files_cache.get(c['id'], [])
            all_files.update(files)
            # 主 commit：標題含 Issue #xxx
            if 'Issue #' in c['title'] or 'issue #' in c['title'].lower():
                main_commit = c
            else:
                impl_commits.append(c)
        
        # 若沒有明確主 commit，用第一筆
        if not main_commit and issue_commits:
            main_commit = issue_commits[0]
            impl_commits = issue_commits[1:]
        
        # 品質分級：以主 commit 為主，輔以實作 commits
        quality = 'unclear'
        if main_commit:
            quality = classify_commit_quality(
                main_commit['title'], 
                main_commit['message'],
                list(all_files)
            )
            # 若主 commit 是 feature，但有實作 commit 是 fix，提升等級
            if quality == 'feature_support':
                for ic in impl_commits:
                    q = classify_commit_quality(ic['title'], ic['message'], [])
                    if q == 'clear_technical_fix':
                        quality = 'feature_with_fix'
                        break
        
        quality_stats[quality] += 1
        
        # 只保留有價值的類型
        if quality in ('clear_technical_fix', 'feature_with_fix', 'feature_support'):
            pairs.append({
                'issue_number': issue_num,
                'issue_ref': f"Issue #{issue_num}",
                'quality': quality,
                'main_commit': {
                    'hash': main_commit['id'] if main_commit else None,
                    'short_id': main_commit['short_id'] if main_commit else None,
                    'title': main_commit['title'] if main_commit else None,
                    'message': main_commit['message'] if main_commit else None,
                    'date': main_commit['created_at'] if main_commit else None,
                    'author': main_commit['author_name'] if main_commit else None,
                } if main_commit else None,
                'impl_commits': [
                    {
                        'hash': ic['id'],
                        'short_id': ic['short_id'],
                        'title': ic['title'],
                        'message': ic['message'],
                        'date': ic['created_at'],
                        'author': ic['author_name'],
                    }
                    for ic in impl_commits
                ],
                'all_changed_files': sorted(list(all_files)),
                'commit_count': len(issue_commits),
            })
    
    # 5. 輸出結果
    print("\n[5/5] 輸出結果...")
    
    clear_fix = quality_stats.get('clear_technical_fix', 0)
    feature_fix = quality_stats.get('feature_with_fix', 0)
    feature = quality_stats.get('feature_support', 0)
    maint = quality_stats.get('maintenance', 0)
    unclear = quality_stats.get('unclear', 0)
    noise = quality_stats.get('exclude_noise', 0)
    
    total_valuable = clear_fix + feature_fix + feature
    
    print("\n" + "=" * 60)
    print("【CP-30-A 完整盤點結果】")
    print("=" * 60)
    print(f"總 commits: {len(commits)}")
    print(f"含 Issue # 的 commits: {commits_with_issue} ({commits_with_issue/len(commits)*100:.1f}%)")
    print(f"獨立 Issue 編號數: {len(issue_groups)}")
    print(f"\n品質分布：")
    print(f"  明確技術修復: {clear_fix}")
    print(f"  功能支援+修復: {feature_fix}")
    print(f"  純功能支援: {feature}")
    print(f"  一般維護: {maint}")
    print(f"  不明確: {unclear}")
    print(f"  雜訊(排除): {noise}")
    print(f"\n可用於驗證集的配對數: {total_valuable}")
    if total_valuable < 15:
        print(f"  ⚠️  少於 15 組門檻，可能原因：專案以新增板卡支援為主、Bug fix 比例低")
    else:
        print(f"  ✅ 達到 15 組門檻，可支撐正式驗證集")
    
    output = {
        'project_id': GITLAB_PROJECT,
        'project_name': 'aaeonFramework',
        'total_commits': len(commits),
        'commits_with_issue_ref': commits_with_issue,
        'unique_issue_numbers': len(issue_groups),
        'quality_distribution': dict(quality_stats),
        'valuable_pairs_count': total_valuable,
        'pairs': pairs,
    }
    
    out_path = Path(__file__).parent / "cp30_a_inventory.json"
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"\n✅ 完整清單已輸出: {out_path}")
    print("\n=== CP-30-A 完成，等待確認後進入 CP-30-B ===")

if __name__ == "__main__":
    main()