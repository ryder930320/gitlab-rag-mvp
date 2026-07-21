#!/usr/bin/env python3
"""
CP-30-A: GitLab Project 153 歷史資料盤點（分階段、可中斷續跑版）
"""

import os
import re
import json
import time
import gitlab
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

GITLAB_URL = os.getenv("GITLAB_URL")
GITLAB_TOKEN = os.getenv("GITLAB_TOKEN")
GITLAB_PROJECT = os.getenv("GITLAB_PROJECT")

gl = gitlab.Gitlab(GITLAB_URL, private_token=GITLAB_TOKEN)
project = gl.projects.get(GITLAB_PROJECT)

ISSUE_PATTERN = re.compile(r'(?:issue|fixes?|closes?|resolves?)\s*#(\d+)', re.IGNORECASE)
HASH_PATTERN = re.compile(r'#(\d+)')

CACHE_DIR = Path(__file__).parent / "cp30_cache"
CACHE_DIR.mkdir(exist_ok=True)

def save_json(data, filename):
    with open(CACHE_DIR / filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)

def load_json(filename):
    path = CACHE_DIR / filename
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

def extract_issue_numbers(text):
    if not text:
        return []
    matches = ISSUE_PATTERN.findall(text)
    if matches:
        return list(set(matches))
    matches = HASH_PATTERN.findall(text)
    return list(set(matches))

def classify_issue_quality(issue):
    text = f"{issue.get('title', '') or ''} {issue.get('description', '') or ''}".lower()
    
    vague_keywords = [
        'add feature', '新增功能', '新增feature', 'feature request',
        'todo', '待辦', '待完成',
        'refactor', '重構', '重构',
        'update dependency', '更新依賴', '升級版本', 'upgrade version',
        'document', '文檔', '文档', 'readme', '註解', '注释',
        'rename', '重命名', '改名',
        'format', '格式化', 'lint', '排版',
        'chore', '雜項', '維護', '维护',
    ]
    
    tech_keywords = [
        'bug', '錯誤', '错误', 'exception', '異常', '异常',
        'crash', '崩潰', '崩溃', 'fail', '失敗', '失败',
        'memory leak', '記憶體洩漏', '内存泄漏',
        'performance', '效能', '效能問題', 'slow', '緩慢', '缓慢',
        'deadlock', '死鎖', '死锁',
        'timeout', '超時', '超时',
        'race condition', '競態', '竞态',
        'null pointer', '空指標', '空指针',
        'corrupt', '損壞', '损坏',
        'invalid', '無效', '无效',
        'incorrect', '不正確', '不正确',
        'wrong', '錯誤', '错误',
        'broken', '壞掉', '坏掉',
        'fix', '修復', '修正', '修復bug', '修正bug',
        'issue', '問題', '问题',
        'problem', '問題', '问题',
    ]
    
    has_vague = any(kw in text for kw in vague_keywords)
    has_tech = any(kw in text for kw in tech_keywords)
    
    if has_tech and not has_vague:
        return "clear_technical"
    elif has_vague and not has_tech:
        return "vague_feature"
    else:
        return "mixed_or_unclear"

def fetch_commits():
    """分頁拉取所有 commit，支援斷點續傳"""
    cached = load_json("all_commits.json")
    if cached:
        print(f"  從快取載入 {len(cached)} 筆 commits")
        return cached
    
    commits = []
    page = 1
    while True:
        print(f"  拉取 commits 第 {page} 頁...")
        try:
            batch = project.commits.list(page=page, per_page=100, all=True)
            if not batch:
                break
            commits.extend([{
                'id': c.id,
                'short_id': c.short_id,
                'title': c.title,
                'message': c.message,
                'created_at': c.created_at,
                'author_name': c.author_name,
            } for c in batch])
            page += 1
            time.sleep(0.1)
        except Exception as e:
            print(f"  錯誤: {e}")
            break
    
    save_json(commits, "all_commits.json")
    print(f"  完成：共 {len(commits)} 筆 commits")
    return commits

def fetch_issues():
    """分頁拉取所有 issue，支援斷點續傳"""
    cached = load_json("all_issues.json")
    if cached:
        print(f"  從快取載入 {len(cached)} 筆 issues")
        return cached
    
    issues = []
    page = 1
    while True:
        print(f"  拉取 issues 第 {page} 頁...")
        try:
            batch = project.issues.list(page=page, per_page=100, state='all')
            if not batch:
                break
            issues.extend([{
                'iid': issue.iid,
                'title': issue.title,
                'description': issue.description,
                'state': issue.state,
                'created_at': issue.created_at,
                'updated_at': issue.updated_at,
                'labels': issue.labels,
            } for issue in batch])
            page += 1
            time.sleep(0.1)
        except Exception as e:
            print(f"  錯誤: {e}")
            break
    
    save_json(issues, "all_issues.json")
    print(f"  完成：共 {len(issues)} 筆 issues")
    return issues

def fetch_commit_files(commit_id):
    """取得單一 commit 的異動檔案（帶快取）"""
    cache_file = f"commit_files_{commit_id[:8]}.json"
    cached = load_json(cache_file)
    if cached:
        return cached
    
    try:
        commit = project.commits.get(commit_id)
        diffs = commit.diff(get_all=True)
        files = [d['new_path'] if d['new_path'] else d['old_path'] for d in diffs if d.get('new_path') or d.get('old_path')]
        files = list(set(files))
        save_json(files, cache_file)
        return files
    except Exception as e:
        return [f"[ERROR: {e}]"]

def main():
    print("=" * 60)
    print("CP-30-A: GitLab Project 153 歷史資料盤點（分階段版）")
    print("=" * 60)
    
    # 階段 1：拉取 commits
    print("\n[階段 1/4] 取得所有 commits...")
    commits = fetch_commits()
    
    # 階段 2：篩選含 issue 編號的 commits
    print("\n[階段 2/4] 篩選含 issue 編號的 commits...")
    commit_issue_pairs = []
    for i, c in enumerate(commits):
        if i % 50 == 0:
            print(f"  處理中... {i}/{len(commits)}")
        issue_nums = extract_issue_numbers(c['message'])
        if issue_nums:
            files = fetch_commit_files(c['id'])
            for issue_num in issue_nums:
                commit_issue_pairs.append({
                    'commit_hash': c['id'],
                    'commit_short_id': c['short_id'],
                    'commit_title': c['title'],
                    'commit_message': c['message'],
                    'commit_date': c['created_at'],
                    'author_name': c['author_name'],
                    'issue_number': issue_num,
                    'changed_files': files
                })
    
    print(f"  含 issue 編號的 commit 筆數: {len(commit_issue_pairs)}")
    save_json(commit_issue_pairs, "commit_issue_pairs.json")
    
    # 階段 3：拉取 issues
    print("\n[階段 3/4] 取得所有 issues...")
    issues = fetch_issues()
    
    # 階段 4：統計與品質分析
    print("\n[階段 4/4] 統計與品質分析...")
    issue_map = {str(issue['iid']): issue for issue in issues}
    
    unique_issues = set()
    quality_counts = {'clear_technical': 0, 'vague_feature': 0, 'mixed_or_unclear': 0}
    issue_quality_map = {}
    
    for pair in commit_issue_pairs:
        unique_issues.add(pair['issue_number'])
        issue_obj = issue_map.get(pair['issue_number'])
        if issue_obj:
            quality = classify_issue_quality(issue_obj)
            quality_counts[quality] += 1
            issue_quality_map[pair['issue_number']] = quality
        else:
            issue_quality_map[pair['issue_number']] = 'issue_not_found'
    
    # 為所有 issue 加上品質分類
    for issue in issues:
        issue['quality_classification'] = classify_issue_quality(issue)
    
    # 輸出統計
    print("\n" + "=" * 60)
    print("【CP-30-A 盤點結果】")
    print("=" * 60)
    print(f"總 commits 數: {len(commits)}")
    print(f"帶 issue 編號的 commit 筆數: {len(commit_issue_pairs)}")
    print(f"對應的不重複 issue 數: {len(unique_issues)}")
    print(f"\nIssue 品質分布:")
    print(f"  - 明確技術問題: {quality_counts['clear_technical']}")
    print(f"  - 模糊/功能新增: {quality_counts['vague_feature']}")
    print(f"  - 混合/不明確: {quality_counts['mixed_or_unclear']}")
    print(f"  - Issue 不存在: {sum(1 for v in issue_quality_map.values() if v == 'issue_not_found')}")
    
    clear_count = quality_counts['clear_technical']
    total_issues_with_quality = sum(quality_counts.values())
    if total_issues_with_quality > 0:
        ratio = clear_count / total_issues_with_quality * 100
        print(f"\n明確技術問題佔比: {ratio:.1f}% ({clear_count}/{total_issues_with_quality})")
    
    if clear_count < 15:
        print(f"\n⚠️  警告：明確技術問題的 commit-issue 配對只有 {clear_count} 組，少於 15 組門檻")
        print("   可能原因：repo 太新、issue 習慣未落實、commit message 不規範")
    
    # 輸出完整清單 JSON
    output = {
        'project_id': GITLAB_PROJECT,
        'total_commits': len(commits),
        'commit_issue_pairs_count': len(commit_issue_pairs),
        'unique_issues_count': len(unique_issues),
        'quality_distribution': quality_counts,
        'clear_technical_ratio': clear_count / total_issues_with_quality * 100 if total_issues_with_quality > 0 else 0,
        'pairs': commit_issue_pairs,
        'issue_quality_map': issue_quality_map,
        'all_issues': issues
    }
    
    output_path = Path(__file__).parent / "cp30_a_inventory.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"\n✅ 完整清單已輸出: {output_path}")
    print("\n=== CP-30-A 完成，等待確認後進入 CP-30-B ===")

if __name__ == "__main__":
    main()