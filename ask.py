#!/usr/bin/env python3
"""
GitLab RAG 簡易查詢工具 - 自動處理中文編碼
用法:
    python ask.py "您的中文問題"
    python ask.py "english question" --top 3
"""
import sys
import urllib.parse
import urllib.request
import json

BASE_URL = "http://localhost:8001"

def ask(question: str, top_k: int = 5, endpoint: str = "suggest") -> dict:
    """發送查詢，自動處理 URL 編碼"""
    url = f"{BASE_URL}/{endpoint}?question={urllib.parse.quote(question)}&top_k={top_k}"
    try:
        with urllib.request.urlopen(url, timeout=120) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.reason}"}
    except Exception as e:
        return {"error": str(e)}

def main():
    if len(sys.argv) < 2:
        print("用法: python ask.py \"您的問題\" [--top N] [--raw]")
        print("範例: python ask.py \"GPIO 控制怎麼用？\"")
        print("      python ask.py \"how to set device\" --top 3")
        sys.exit(1)

    # 解析參數
    question = sys.argv[1]
    top_k = 5
    raw = False

    for arg in sys.argv[2:]:
        if arg.startswith("--top"):
            top_k = int(arg.split("=")[1]) if "=" in arg else int(sys.argv[sys.argv.index(arg)+1])
        elif arg == "--raw":
            raw = True

    result = ask(question, top_k)

    if "error" in result:
        print(f"❌ {result['error']}")
        return

    if raw:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # 友善輸出
    print(f"\n🔍 問題: {question}")
    print(f"🎯 信心等級: {result.get('confidence', 'N/A')}")
    print(f"💡 理由: {result.get('confidence_reason', 'N/A')}")
    print(f"\n📝 建議內容:\n{result.get('suggestion', 'N/A')}")

    sources = result.get('sources', [])
    if sources:
        print(f"\n📚 引用來源 ({len(sources)} 筆):")
        for i, s in enumerate(sources, 1):
            sid = s.get('source_id', s.get('id', i))
            rrf = s.get('rrf_score', s.get('score', 'N/A'))
            print(f"  [{sid}] {s['file_path']} chunk#{s['chunk_index']} (rrf={rrf})")

if __name__ == "__main__":
    main()