import os
import json
from gitlab_client import list_files, get_file_content, get_recent_commits, project

CODE_EXTS = {'.py', '.js', '.ts', '.java', '.cpp', '.c', '.h', '.go', '.rs', '.md', '.txt', '.json', '.yaml', '.yml', '.toml', '.ini', '.cfg'}

def is_code_file(path: str) -> bool:
    return any(path.endswith(ext) for ext in CODE_EXTS)

def main():
    os.makedirs("data", exist_ok=True)
    
    # 抓取所有檔案路徑
    files = list_files(project)
    print(f"總檔案數: {len(files)}")
    
    # 過濾程式碼檔案
    code_files = [f for f in files if is_code_file(f)]
    print(f"程式碼檔案數: {len(code_files)}")
    
    # 抓取檔案內容
    raw_files = []
    for f in code_files:
        content = get_file_content(project, f)
        if not content.startswith("[ERROR"):
            lang = f.split('.')[-1] if '.' in f else 'text'
            raw_files.append({
                "path": f,
                "content": content,
                "language": lang
            })
    
    # 抓取最近 50 筆 commit
    commits = get_recent_commits(project, limit=50)
    raw_commits = [
        {"title": c["title"], "message": c["message"], "created_at": c["created_at"]}
        for c in commits
    ]
    
    # 存檔
    with open("data/raw_files.json", "w", encoding="utf-8") as f:
        json.dump(raw_files, f, ensure_ascii=False, indent=2)
    
    with open("data/raw_commits.json", "w", encoding="utf-8") as f:
        json.dump(raw_commits, f, ensure_ascii=False, indent=2)
    
    print(f"已寫入 data/raw_files.json: {len(raw_files)} 筆")
    print(f"已寫入 data/raw_commits.json: {len(raw_commits)} 筆")

if __name__ == "__main__":
    main()