#!/usr/bin/env python3
"""
Re-chunk using tiktoken for accurate token counting + boundary-aware splitting
- 使用 cl100k_base tokenizer (接近 nv-embedqa-e5-v5)
- 在函式/結構邊界斷開
- 確保每 chunk ≤ MAX_TOKENS
"""

import json
import os
import re
import tiktoken
from pathlib import Path

DATA_DIR = "data"
CHUNKS_PATH = os.path.join(DATA_DIR, "chunks.json")
RAW_FILES_PATH = os.path.join(DATA_DIR, "raw_files.json")
RAW_COMMITS_PATH = os.path.join(DATA_DIR, "raw_commits.json")
OUTPUT_PATH = os.path.join(DATA_DIR, "chunks_v2.json")

MAX_TOKENS = 300  # 更保守：NVIDIA tokenizer 比 cl100k_base 多 ~29%，300 * 1.29 ≈ 387 < 512
TARGET_TOKENS = 250  # 目標 chunk 大小

enc = tiktoken.get_encoding("cl100k_base")

def count_tokens(text: str) -> int:
    return len(enc.encode(text))

def find_c_boundaries(content: str) -> list:
    """找出 C/C++ 適合斷開的位置（函式、結構、巨集、大括號層級）"""
    boundaries = [0]
    lines = content.splitlines(keepends=True)
    char_pos = 0
    brace_level = 0
    
    func_pattern = re.compile(r'^\s*(?:static\s+)?(?:inline\s+)?(?:[a-zA-Z_][a-zA-Z0-9_*\s]+)\s+[a-zA-Z_][a-zA-Z0-9_]*\s*\([^)]*\)\s*\{')
    struct_pattern = re.compile(r'^\s*(?:typedef\s+)?(?:struct|union|enum)\s+[a-zA-Z_][a-zA-Z0-9_]*\s*\{')
    macro_pattern = re.compile(r'^\s*#\s*(?:define|ifdef|ifndef|endif|pragma)')
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        is_boundary = False
        
        # 1. 空行
        if stripped == '':
            is_boundary = True
        
        # 2. 函式定義
        elif func_pattern.match(line):
            is_boundary = True
        
        # 3. 結構體/聯合/列舉
        elif struct_pattern.match(line):
            is_boundary = True
        
        # 4. 前置處理器指令
        elif macro_pattern.match(line):
            is_boundary = True
        
        # 5. 大括號層級歸零（函式結束）
        elif '{' in line or '}' in line:
            for ch in line:
                if ch == '{':
                    brace_level += 1
                elif ch == '}':
                    brace_level -= 1
            if brace_level == 0 and i + 1 < len(lines):
                next_stripped = lines[i + 1].strip()
                if not next_stripped.startswith(('else', 'while', 'catch')):
                    is_boundary = True
        
        if is_boundary and char_pos > 0:
            boundaries.append(char_pos)
        
        char_pos += len(line)
    
    boundaries.append(len(content))
    return sorted(set(boundaries))

def chunk_by_boundaries(content: str, language: str, max_tokens: int = MAX_TOKENS) -> list:
    """在邊界處切分，必要時硬切"""
    if count_tokens(content) <= max_tokens:
        return [content]
    
    if language in ('c', 'h', 'cpp', 'cc', 'cxx'):
        boundaries = find_c_boundaries(content)
    else:
        # 通用：空行、縮層變化
        boundaries = [0]
        lines = content.splitlines(keepends=True)
        char_pos = 0
        for line in lines:
            if line.strip() == '' and char_pos > 0:
                boundaries.append(char_pos)
            char_pos += len(line)
        boundaries.append(len(content))
    
    chunks = []
    start_idx = 0
    
    while start_idx < len(boundaries) - 1:
        best_end = start_idx + 1
        
        # 往前找最遠不超過 max_tokens 的邊界
        for end_idx in range(start_idx + 1, len(boundaries)):
            chunk_text = content[boundaries[start_idx]:boundaries[end_idx]]
            if count_tokens(chunk_text) > max_tokens:
                break
            best_end = end_idx
        
        # 如果連下一個邊界都超過，硬切
        if best_end == start_idx + 1:
            chunk_text = content[boundaries[start_idx]:boundaries[start_idx + 1]]
            tokens = enc.encode(chunk_text)
            if len(tokens) > max_tokens:
                # 截斷到 max_tokens 再找最近空白
                truncated = enc.decode(tokens[:max_tokens])
                last_space = max(truncated.rfind(' '), truncated.rfind('\n'), truncated.rfind('\t'))
                if last_space > len(truncated) * 0.5:
                    truncated = truncated[:last_space]
                chunks.append(truncated)
                # 剩餘遞歸處理
                remaining = content[boundaries[start_idx] + len(truncated):]
                sub_chunks = chunk_by_boundaries(remaining, language, max_tokens)
                chunks.extend(sub_chunks)
                break
            else:
                best_end = start_idx + 1
        
        chunk_text = content[boundaries[start_idx]:boundaries[best_end]]
        chunks.append(chunk_text)
        start_idx = best_end
    
    return chunks

def main():
    # 讀取原始檔案
    with open(RAW_FILES_PATH, 'r', encoding='utf-8') as f:
        raw_files = json.load(f)
    with open(RAW_COMMITS_PATH, 'r', encoding='utf-8') as f:
        raw_commits = json.load(f)
    
    print(f"原始檔案: {len(raw_files)} 筆")
    print(f"原始 commits: {len(raw_commits)} 筆")
    
    chunks = []
    chunk_idx = 0
    
    # 處理程式碼檔案
    for item in raw_files:
        path = item["path"]
        content = item["content"]
        lang = item.get("language", "")
        
        if not content.strip():
            continue
        
        file_chunks = chunk_by_boundaries(content, lang)
        
        for i, ch in enumerate(file_chunks):
            token_count = count_tokens(ch)
            chunks.append({
                "content": ch,
                "metadata": {
                    "source_type": "code",
                    "file_path": path,
                    "language": lang,
                    "chunk_index": i,
                    "global_chunk_id": chunk_idx,
                    "token_count": token_count
                }
            })
            chunk_idx += 1
    
    # 處理 commits
    for i, commit in enumerate(raw_commits):
        full_msg = f"{commit['title']}\n{commit['message']}".strip()
        token_count = count_tokens(full_msg)
        
        # Commit 通常很短，但以防萬一
        if token_count > MAX_TOKENS:
            msg_chunks = chunk_by_boundaries(full_msg, 'text', MAX_TOKENS)
            for j, msg_ch in enumerate(msg_chunks):
                chunks.append({
                    "content": msg_ch,
                    "metadata": {
                        "source_type": "commit",
                        "file_path": None,
                        "language": None,
                        "chunk_index": j,
                        "global_chunk_id": chunk_idx,
                        "token_count": count_tokens(msg_ch),
                        "created_at": commit.get("created_at", "")
                    }
                })
                chunk_idx += 1
        else:
            chunks.append({
                "content": full_msg,
                "metadata": {
                    "source_type": "commit",
                    "file_path": None,
                    "language": None,
                    "chunk_index": 0,
                    "global_chunk_id": chunk_idx,
                    "token_count": token_count,
                    "created_at": commit.get("created_at", "")
                }
            })
            chunk_idx += 1
    
    # 統計
    code_chunks = [c for c in chunks if c["metadata"]["source_type"] == "code"]
    commit_chunks = [c for c in chunks if c["metadata"]["source_type"] == "commit"]
    token_counts = [c["metadata"]["token_count"] for c in code_chunks]
    
    print(f"\n總 chunks: {len(chunks)}")
    print(f"  程式碼: {len(code_chunks)}")
    print(f"  commits: {len(commit_chunks)}")
    print(f"Token 統計 (程式碼):")
    print(f"  最大: {max(token_counts)}")
    print(f"  平均: {sum(token_counts)/len(token_counts):.1f}")
    print(f"  ≤500: {sum(1 for t in token_counts if t <= 500)}")
    print(f"  501-512: {sum(1 for t in token_counts if 500 < t <= 512)}")
    print(f"  >512: {sum(1 for t in token_counts if t > 512)}")
    
    # 儲存
    Path(OUTPUT_PATH).parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)
    
    print(f"\n已輸出: {OUTPUT_PATH}")

if __name__ == "__main__":
    main()