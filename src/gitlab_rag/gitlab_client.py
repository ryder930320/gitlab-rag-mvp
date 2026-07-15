import os
import gitlab
from dotenv import load_dotenv

load_dotenv()

GITLAB_URL = os.getenv("GITLAB_URL")
GITLAB_TOKEN = os.getenv("GITLAB_TOKEN")
GITLAB_PROJECT = os.getenv("GITLAB_PROJECT")

gl = gitlab.Gitlab(GITLAB_URL, private_token=GITLAB_TOKEN)
project = gl.projects.get(GITLAB_PROJECT)


def list_files(project) -> list[str]:
    """回傳 repo 內所有檔案路徑"""
    items = project.repository_tree(recursive=True, all=True)
    files = [item['path'] for item in items if item['type'] == 'blob']
    return files


def get_file_content(project, file_path: str, ref: str = "main") -> str:
    """回傳指定檔案的原始內容"""
    try:
        file_obj = project.files.get(file_path=file_path, ref=ref)
        content = file_obj.decode()
        if isinstance(content, bytes):
            content = content.decode('utf-8', errors='replace')
        return content
    except Exception as e:
        return f"[ERROR reading {file_path}: {e}]"


def get_recent_commits(project, limit: int = 30) -> list[dict]:
    """回傳最近 N 筆 commit，含 title、message、created_at"""
    commits = project.commits.list(all=True, per_page=limit)
    result = []
    for c in commits:
        result.append({
            "title": c.title,
            "message": c.message,
            "created_at": c.created_at
        })
    return result


if __name__ == "__main__":
    print("=== 測試 gitlab_client.py ===")
    
    # 測試 list_files
    files = list_files(project)
    print(f"\n檔案總數: {len(files)}")
    print("前 5 個檔案路徑:")
    for f in files[:5]:
        print(f"  {f}")
    
    # 測試 get_recent_commits
    commits = get_recent_commits(project, limit=3)
    print("\n前 3 筆 commit title:")
    for c in commits:
        print(f"  {c['title']}")
    
    # 測試 get_file_content (讀取第一個檔案)
    if files:
        content = get_file_content(project, files[0])
        print(f"\n第一個檔案內容預覽 ({files[0]}):")
        print(content[:200] + ("..." if len(content) > 200 else ""))