#!/usr/bin/env python
"""
CP-25: 評估框架 - Faithfulness 指標實作 (多次評審取中位數版本)

此腳本使用 CP-20 執行時產生的 test_results_full.json 快取結果
(包含檢索結果 + 生成建議) 進行 Faithfulness 評估。

當 NIM API 額度恢復時，可改為即時跑 generate_coding_suggestion()。

評估流程：
1. 載入 golden_test_set.json (測試案例定義)
2. 載入 test_results_full.json (CP-20 執行結果：retrieval + generation)
3. 對 18 題有效評估案例進行 Faithfulness 評估 (每題跑
4. 每題跑 N 次 (預設 3)，取中位數作為穩定分數
5. 輸出基準分數與詳細分佈

改進自 CP-25 Step 3：解決 LLM-as-Judge 非確定性問題
"""

import json
import os
import sys
import time
import statistics
from pathlib import Path
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv

PROJECT_ROOT = Path.cwd()
GITLAB_RAG_ROOT = PROJECT_ROOT
# Fix: avoid double gitlab-rag-mvp in path
if not GITLAB_RAG_ROOT.exists():
    GITLAB_RAG_ROOT = PROJECT_ROOT
sys.path.insert(0, str(GITLAB_RAG_ROOT / "src"))

load_dotenv(GITLAB_RAG_ROOT / ".env")

NIM_API_KEY = os.getenv("NIM_API_KEY")
NIM_GENERATE_MODEL = os.getenv("NIM_GENERATE_MODEL", "nvidia/nemotron-3-ultra-550b-a55b")
NIM_GENERATE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

import httpx

from .nim_logger import log_nim_call

# 預設評審次數 (CP-25 Step 3: 多次取中位數解決非確定性)
DEFAULT_N_RUNS = 3


def call_nim_judge(prompt: str, timeout: float = 120.0) -> str:
    """呼叫 NIM 模型作為評審，並記錄到 nim_logger (CP-26)"""
    if not NIM_API_KEY:
        raise RuntimeError("請先設定 .env 中的 NIM_API_KEY")

    headers = {
        "Authorization": f"Bearer {NIM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": NIM_GENERATE_MODEL,
        "messages": [
            {"role": "system", "content": "You are a JSON-only API. Your ONLY output must be a single valid JSON object matching the user's schema. No reasoning, no explanation, no conversation, no markdown. If you output anything other than the JSON object, you have failed."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.0,
        "max_tokens": 8192,
        "stream": False,
    }

    start = time.time()
    error_msg = None
    response_json = None
    status_code = 0
    finish_reason = None

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(NIM_GENERATE_URL, headers=headers, json=payload)
            latency_ms = int((time.time() - start) * 1000)
            status_code = resp.status_code
            if resp.status_code == 402:
                raise RuntimeError("NIM API 額度用盡 (HTTP 402)")
            if resp.status_code == 429:
                raise RuntimeError("NIM API 速率限制 (HTTP 429)")
            resp.raise_for_status()
            data = resp.json()
            response_json = data
            finish_reason = data["choices"][0].get("finish_reason")
            return data["choices"][0]["message"]["content"].strip()
    except httpx.TimeoutException:
        latency_ms = int((time.time() - start) * 1000)
        raise RuntimeError(f"NIM API 請求逾時 ({timeout} 秒)")
    except httpx.HTTPStatusError as e:
        latency_ms = int((time.time() - start) * 1000)
        status_code = e.response.status_code
        raise RuntimeError(f"NIM API HTTP 錯誤: {e.response.status_code} - {e.response.text}")
    except Exception as e:
        latency_ms = int((time.time() - start) * 1000)
        error_msg = str(e)
        raise RuntimeError(f"NIM API 呼叫失敗: {e}")
    finally:
        # Log to nim_logger (CP-26)
        log_nim_call(
            query=prompt[:200] + "..." if len(prompt) > 200 else prompt,
            model=NIM_GENERATE_MODEL,
            call_type="evaluate_faithfulness",
            request_payload=payload,
            response_payload=response_json,
            finish_reason=finish_reason,
            fallback_triggered=False,
            latency_ms=latency_ms,
            error=error_msg,
            status_code=status_code,
        )


def build_chunks_text(sources: List[Dict]) -> str:
    """將 sources 格式化為評審用的 chunks 文字"""
    if not sources:
        return "(無檢索結果)"
    blocks = []
    for s in sources:
        preview = s.get("preview", "")
        if len(preview) > 800:
            preview = preview[:800] + "...[截斷]"
        blocks.append(f"[來源 {s['source_id']}] 檔案: {s['file_path']} (chunk #{s['chunk_index']})\n{preview}")
    return "\n\n---\n\n".join(blocks)


def parse_judge_response(response: str) -> Dict:
    """解析評審回應 JSON - 嚴格模式：只接受第一個完整 JSON 物件"""
    import re

    # 嘗試直接解析
    try:
        return json.loads(response.strip())
    except json.JSONDecodeError:
        pass

    # 找到第一個 { 並提取完整的 JSON 物件（支援巢狀）
    start = response.find('{')
    if start != -1:
        brace_count = 0
        for i, ch in enumerate(response[start:], start):
            if ch == '{':
                brace_count += 1
            elif ch == '}':
                brace_count -= 1
                if brace_count == 0:
                    json_str = response[start:i+1]
                    try:
                        return json.loads(json_str)
                    except json.JSONDecodeError:
                        break

    raise RuntimeError(f"評審回應非有效 JSON (前500字元): {response[:500]}")


def load_golden_test_set() -> Dict:
    """載入黃金測試集"""
    path = GITLAB_RAG_ROOT / "src" / "gitlab_rag" / "golden_test_set.json"
    if not path.exists():
        # Fallback: try relative to PROJECT_ROOT
        path = PROJECT_ROOT / "src" / "gitlab_rag" / "golden_test_set.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_cached_results() -> Dict:
    """載入 CP-20 執行快取結果"""
    path = GITLAB_RAG_ROOT / "test_results_full.json"
    if not path.exists():
        path = PROJECT_ROOT / "test_results_full.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_cached_result(cached_results: Dict, question: str) -> Optional[Dict]:
    """從快取結果中找到對應題目的結果"""
    # 直接匹配
    if question in cached_results:
        return cached_results[question]
    # 模糊匹配
    for k, v in cached_results.items():
        if question in k or k in question:
            return v
    return None


def generate_fresh_result(question: str, top_k: int = 5) -> Dict:
    """即時呼叫 generate_coding_suggestion() 產生新結果 (用於無快取的查詢)"""
    sys.path.insert(0, str(GITLAB_RAG_ROOT / "src"))
    from gitlab_rag.generate_coding_suggestion import generate_coding_suggestion

    print(f"  即時生成: {question[:40]}...")
    result = generate_coding_suggestion(question, top_k=top_k)
    return {
        "retrieval": result.get("sources", []),
        "generation": {
            "suggestion": result.get("suggestion", ""),
            "confidence": result.get("confidence", ""),
            "confidence_reason": result.get("confidence_reason", ""),
            "sources": result.get("sources", []),
            "error": result.get("error")
        }
    }


def evaluate_faithfulness_single(query: str, cached_result: Dict) -> Dict:
    """對單一查詢進行單次 Faithfulness 評估"""
    sources = cached_result.get("generation", {}).get("sources", [])
    suggestion = cached_result.get("generation", {}).get("suggestion", "")

    if not suggestion or suggestion.startswith("❌ 生成失敗"):
        return {
            "query": query,
            "error": "Generation failed or empty",
            "faithfulness_score": 0.0,
            "claims": [],
            "summary": "No valid generation to evaluate",
            "supported_count": 0,
            "not_supported_count": 0,
            "partial_count": 0,
            "general_advice_count": 0
        }

    chunks_text = build_chunks_text(sources)

    # Use f-string to avoid template brace conflicts
    prompt = f"""Task: Faithfulness evaluation. Output ONLY valid JSON matching the schema.

Query: {query}

Retrieved chunks (relevance-ranked):
{chunks_text}

Generated answer:
{suggestion}

Instructions:
- Break answer into specific claims
- For each claim, check if chunks contain supporting evidence
- Label: SUPPORTED (explicit in chunks), NOT_SUPPORTED (no evidence = hallucination), PARTIAL (some evidence but incomplete), GENERAL_ADVICE (explicitly marked as non-repo general advice)
- Score = SUPPORTED / (SUPPORTED + NOT_SUPPORTED + PARTIAL). GENERAL_ADVICE excluded from denominator.
- Output ONLY this JSON schema (no reasoning, no text, no markdown):

{{
  "claims": [{{
    "claim": "string",
    "type": "SUPPORTED|NOT_SUPPORTED|PARTIAL|GENERAL_ADVICE",
    "evidence_chunk": "string",
    "reason": "string"
  }}],
  "faithfulness_score": 0.0,
  "summary": "string",
  "supported_count": 0,
  "not_supported_count": 0,
  "partial_count": 0,
  "general_advice_count": 0
}}"""

    print(f"  呼叫評審模型... (prompt: {len(prompt)} chars)")
    response = call_nim_judge(prompt)
    print(f"  回應長度: {len(response)} chars")
    print(f"  回應前200字元: {response[:200]}")

    result = parse_judge_response(response)
    print(f"  解析結果: {type(result)}, keys={list(result.keys()) if isinstance(result, dict) else 'N/A'}")

    return {
        "query": query,
        "faithfulness_score": result.get("faithfulness_score", 0.0),
        "claims": result.get("claims", []),
        "summary": result.get("summary", ""),
        "supported_count": result.get("supported_count", 0),
        "not_supported_count": result.get("not_supported_count", 0),
        "partial_count": result.get("partial_count", 0),
        "general_advice_count": result.get("general_advice_count", 0),
        "raw_response": response
    }


def evaluate_faithfulness_multi_run(query: str, cached_result: Dict, n_runs: int = DEFAULT_N_RUNS) -> Dict:
    """對單一查詢進行多次 Faithfulness 評估，取中位數"""
    print(f"\n  開始 {n_runs} 次評審跑分...")

    all_scores = []
    all_results = []

    for run_idx in range(n_runs):
        print(f"    Run {run_idx + 1}/{n_runs}...")
        try:
            result = evaluate_faithfulness_single(query, cached_result)
            score = result.get("faithfulness_score")
            if score is not None:
                all_scores.append(score)
                all_results.append(result)
                print(f"      Score: {score:.4f}")
            else:
                print(f"      無有效分數")
        except Exception as e:
            print(f"      ✗ 評估失敗: {e}")
            import traceback
            traceback.print_exc()

        # 避免速率限制，短暫延遲
        if run_idx < n_runs - 1:
            time.sleep(1.0)

    if not all_scores:
        return {
            "query": query,
            "error": "All runs failed",
            "faithfulness_score": None,
            "scores_distribution": [],
            "median_score": None,
            "mad": None,
            "individual_results": all_results
        }

    median_score = statistics.median(all_scores)
    mad = statistics.median([abs(s - median_score) for s in all_scores]) if len(all_scores) > 1 else 0.0

    # 找到中位數對應的那次結果（如果有多個相同中位數，取第一個）
    median_result = None
    for r in all_results:
        if r.get("faithfulness_score") == median_score:
            median_result = r
            break
    if median_result is None:
        # 取最接近中位數的
        median_result = min(all_results, key=lambda r: abs(r.get("faithfulness_score", 0) - median_score))

    return {
        "query": query,
        "faithfulness_score": median_score,
        "scores_distribution": all_scores,
        "median_score": median_score,
        "mad": mad,
        "n_runs": n_runs,
        "n_valid": len(all_scores),
        "claims": median_result.get("claims", []),
        "summary": median_result.get("summary", ""),
        "supported_count": median_result.get("supported_count", 0),
        "not_supported_count": median_result.get("not_supported_count", 0),
        "partial_count": median_result.get("partial_count", 0),
        "general_advice_count": median_result.get("general_advice_count", 0),
        "individual_results": all_results
    }


def main(n_runs: int = DEFAULT_N_RUNS):
    print("=" * 60)
    print(f"CP-25 Step 3: 評估框架 - Faithfulness 基準測試 (多次取中位數, n={n_runs})")
    print("=" * 60)

    # 1. 載入測試集定義
    golden = load_golden_test_set()
    test_cases = golden["test_cases"]

    # 篩選出有效評估案例 (排除 removed 類別)
    valid_cases = [tc for tc in test_cases if "removed" not in tc["category"]]
    print(f"\n有效評估案例: {len(valid_cases)} 題")
    for tc in valid_cases:
        print(f"  {tc['id']}: {tc['question']} (category: {tc['category']})")

    # 2. 載入快取結果
    cached_results = load_cached_results()
    print(f"\n快取結果載入: {len(cached_results)} 題")

    # 3. 逐題評估 (多次取中位數)
    evaluation_results = []
    scores = []

    for i, tc in enumerate(valid_cases, 1):
        q = tc["question"]
        print(f"\n[{i}/{len(valid_cases)}] 評估: {q}")
        print(f"  分類: {tc['category']}, 標籤品質: {tc['label_quality']}")
        print(f"  預期信心: {tc['expected_confidence']}")

        cached = get_cached_result(cached_results, q)
        if not cached:
            print(f"  快取中找不到，即時生成...")
            try:
                cached = generate_fresh_result(q)
                print(f"  即時生成完成")
            except Exception as e:
                print(f"  ✗ 即時生成失敗: {e}")
                evaluation_results.append({
                    "query": q,
                    "test_case": tc,
                    "error": f"Generation failed: {e}",
                    "faithfulness_score": None
                })
                continue

        try:
            eval_result = evaluate_faithfulness_multi_run(q, cached, n_runs=n_runs)
            eval_result["test_case"] = tc
            evaluation_results.append(eval_result)

            score = eval_result.get("faithfulness_score")
            if score is not None:
                scores.append(score)
                print(f"  ✓ 中位數 Faithfulness Score: {score:.4f}")
                print(f"    所有分數: {[f'{s:.4f}' for s in eval_result['scores_distribution']]}")
                print(f"    MAD: {eval_result['mad']:.4f}")
                sc = eval_result.get('supported_count', 'N/A')
                nsc = eval_result.get('not_supported_count', 'N/A')
                pc = eval_result.get('partial_count', 'N/A')
                gac = eval_result.get('general_advice_count', 'N/A')
                print(f"    Supported: {sc}, Not Supported: {nsc}, Partial: {pc}, General Advice: {gac}")
                print(f"    有效評審次數: {eval_result['n_valid']}/{eval_result['n_runs']}")
            else:
                print(f"  ✗ 無有效分數")
        except Exception as e:
            import traceback
            print(f"  ✗ 評估失敗: {e}")
            print(f"  Traceback: {traceback.format_exc()}")
            evaluation_results.append({
                "query": q,
                "test_case": tc,
                "error": str(e),
                "faithfulness_score": None
            })

    # 4. 輸出總結
    print("\n" + "=" * 60)
    print("CP-25 Step 3 基準評估結果總結")
    print("=" * 60)

    valid_scores = [s for s in scores if s is not None]
    if valid_scores:
        avg_score = sum(valid_scores) / len(valid_scores)
        median_overall = statistics.median(valid_scores)
        print(f"\n有效評估: {len(valid_scores)}/{len(valid_cases)} 題")
        print(f"平均 Faithfulness Score: {avg_score:.4f}")
        print(f"整體中位數: {median_overall:.4f}")
        print(f"分數分佈: min={min(valid_scores):.4f}, max={max(valid_scores):.4f}")
        print(f"個別中位數分數: {[f'{s:.4f}' for s in valid_scores]}")
    else:
        print("無有效分數 (可能因 API 額度限制)")

    # 5. 儲存詳細結果
    output = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "evaluation_method": f"LLM-as-Judge (Nemotron-3-Ultra) on cached CP-20 results + fresh CP-22, median of {n_runs} runs",
        "golden_test_set_version": golden.get("version", "1.0"),
        "n_runs_per_query": n_runs,
        "total_cases_evaluated": len(valid_cases),
        "valid_evaluations": len(valid_scores),
        "average_faithfulness_score": avg_score if valid_scores else None,
        "overall_median_score": median_overall if valid_scores else None,
        "individual_scores": {r["query"]: r.get("faithfulness_score") for r in evaluation_results},
        "score_distributions": {r["query"]: r.get("scores_distribution", []) for r in evaluation_results},
        "median_scores": {r["query"]: r.get("median_score") for r in evaluation_results},
        "mads": {r["query"]: r.get("mad") for r in evaluation_results},
        "n_valid_per_query": {r["query"]: r.get("n_valid") for r in evaluation_results},
        "detailed_results": evaluation_results,
        "limitations": {
            "llm_judge_error_rate": "文獻報告 LLM-as-judge 與人工標註約 5-15% 不一致",
            "single_model_bias": "單一評審模型可能有系統性偏好",
            "non_deterministic": f"評審模型輸出具非確定性，本次採用 {n_runs} 次取中位數緩解；實測同一題同一答案三次評審分數可相差 5-6 倍 (如「危險區域」0.400 vs 0.071，MAD=0.164)，LLM-as-judge 離散程度遠超 reranker 非確定性 (±0.05)，MAD 單一數值無法完整反映極端離散風險",
            "cached_generation": "CP-20 8 題使用 CP-20 快取生成結果；CP-22 10 題即時生成；後續改動 pipeline 後需重跑",
            "scope": "僅評估 18 題有效案例 (8 CP-20 + 10 CP-22 cleaned)",
            "sample_size_variation": f"部分題目有效評審次數 < 3 (n_valid < n_runs)，詳見 n_valid_per_query；n_valid=1 的題目（如 react vue angular 前端）僅為單次評審，其分數權重與 3/3 題目相同，可能導致整體平均失真"
        }
    }

    out_path = GITLAB_RAG_ROOT / "cp25_faithfulness_baseline_v2.json"
    if not GITLAB_RAG_ROOT.exists():
        out_path = PROJECT_ROOT / "cp25_faithfulness_baseline_v2.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n詳細結果已寫入: {out_path}")

    # 顯示每題詳細統計
    print("\n=== 各題詳細統計 ===")
    for r in evaluation_results:
        if r.get("faithfulness_score") is not None:
            q_short = r["query"][:40] + "..." if len(r["query"]) > 40 else r["query"]
            dist = r.get("scores_distribution", [])
            n_valid = r.get("n_valid", 0)
            n_runs = r.get("n_runs", 3)
            print(f"  {q_short}")
            print(f"    Scores: {[f'{s:.3f}' for s in dist]}")
            print(f"    Median: {r['median_score']:.4f}, MAD: {r['mad']:.4f}, Valid runs: {n_valid}/{n_runs}")

    return 0


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="CP-25 Faithfulness Evaluation with median-of-N runs")
    parser.add_argument("--n-runs", type=int, default=DEFAULT_N_RUNS, help=f"Number of evaluation runs per query (default: {DEFAULT_N_RUNS})")
    args = parser.parse_args()

    sys.exit(main(n_runs=args.n_runs))