"""FastAPI wrapper for GitLab RAG - HTTP endpoint for Hermes
包含階段延遲追蹤 + SSE 串流端點"""
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
import asyncio
import json
import os
import time
import contextlib
import httpx

from ..core.rag_interface import query_gitlab_context, get_coding_suggestion

app = FastAPI(title="GitLab RAG MVP", version="0.1.0")

# CORS for local HTML file (file://) and any origin during development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class QueryRequest(BaseModel):
    question: str
    top_k: int = 5
    use_hybrid: bool = True


class Hit(BaseModel):
    content: str
    file_path: str
    source_type: str
    language: str
    chunk_index: int
    created_at: str
    score: float


class QueryResponse(BaseModel):
    question: str
    results: List[Hit]
    count: int


class Source(BaseModel):
    file_path: str
    chunk_index: int
    preview: str


class SuggestionResponse(BaseModel):
    question: str
    suggestion: str
    confidence: str
    confidence_reason: str
    sources: List[Source]


class TimingInfo(BaseModel):
    """各階段延遲資訊 (ms)"""
    query_expand_ms: float = 0
    embedding_ms: float = 0
    hybrid_search_ms: float = 0
    confidence_eval_ms: float = 0
    prompt_build_ms: float = 0
    llm_generate_ms: float = 0
    total_ms: float = 0


class SuggestionResponseWithTiming(BaseModel):
    question: str
    suggestion: str
    confidence: str
    confidence_reason: str
    sources: List[dict]
    timings: Optional[dict] = None


# ===== 同步端點（保持原有功能）=====

@app.get("/query", response_model=QueryResponse)
def query_get(
    question: str = Query(..., description="使用者問題"),
    top_k: int = Query(5, ge=1, le=20),
    use_hybrid: bool = Query(True, description="是否使用混合檢索（向量+BM25），False 退回純向量")
):
    """GET 端點：/query?question=xxx&top_k=5&use_hybrid=true"""
    from ..core.rag_interface import query_gitlab_context
    hits = query_gitlab_context(question, top_k=top_k, use_hybrid=use_hybrid)
    return QueryResponse(
        question=question,
        results=[Hit(**h) for h in hits],
        count=len(hits)
    )


@app.post("/query", response_model=QueryResponse)
def query_post(req: QueryRequest):
    """POST 端點：/query {question, top_k, use_hybrid}"""
    from ..core.rag_interface import query_gitlab_context
    hits = query_gitlab_context(req.question, top_k=req.top_k, use_hybrid=req.use_hybrid)
    return QueryResponse(
        question=req.question,
        results=[Hit(**h) for h in hits],
        count=len(hits)
    )


@app.post("/suggest", response_model=dict)
def suggest_post(req: QueryRequest):
    """POST 端點：/suggest {question, top_k, use_hybrid} - 回傳完整程式碼建議"""
    result = get_coding_suggestion(req.question, top_k=req.top_k)
    return result


@app.get("/suggest", response_model=dict)
def suggest_get(
    question: str = Query(..., description="使用者問題"),
    top_k: int = Query(5, ge=1, le=20),
    use_hybrid: bool = Query(True, description="是否使用混合檢索")
):
    """GET 端點：/suggest?question=xxx&top_k=5&use_hybrid=true"""
    result = get_coding_suggestion(question, top_k=top_k)
    return result


@app.get("/suggest/timing")
def suggest_with_timing(
    question: str = Query(..., description="使用者問題"),
    top_k: int = Query(5, ge=1, le=20),
    use_hybrid: bool = Query(True, description="是否使用混合檢索")
):
    """GET 端點：回傳完整建議 + 詳細階段延遲"""
    from ..core.hybrid_search import hybrid_search
    from ..core.confidence_evaluator import evaluate_confidence
    from ..core.prompt_builder import build_prompt
    from ..core.generate_coding_suggestion import call_nim_generate
    import time

    timings = {}
    start_total = time.perf_counter()

    # 1. Hybrid Search (內含 embedding + BM25 + RRF)
    t0 = time.perf_counter()
    raw_results = hybrid_search(question, top_k=top_k)
    timings['hybrid_search_ms'] = (time.perf_counter() - t0) * 1000

    # 2. Confidence
    t0 = time.perf_counter()
    confidence = evaluate_confidence(raw_results[:top_k])
    timings['confidence_eval_ms'] = (time.perf_counter() - t0) * 1000

    # 3. Prompt Build
    t0 = time.perf_counter()
    prompt = build_prompt(question, raw_results[:top_k], top_k=top_k)
    timings['prompt_build_ms'] = (time.perf_counter() - t0) * 1000

    # 4. LLM Generate
    t0 = time.perf_counter()
    suggestion = call_nim_generate(prompt)
    timings['llm_generate_ms'] = (time.perf_counter() - t0) * 1000

    timings['total_ms'] = (time.perf_counter() - start_total) * 1000

    # 5. 整理 sources（直接用已取得的 raw_results，避免重跑完整流程）
    sources = []
    for i, chunk in enumerate(raw_results[:top_k], 1):
        sources.append({
            "source_id": i,
            "file_path": chunk.get("file_path", ""),
            "chunk_index": chunk.get("chunk_index", 0),
            "preview": chunk.get("content", "")[:200] + ("..." if len(chunk.get("content", "")) > 200 else ""),
            "rrf_score": chunk.get("rrf_score", 0.0),
            "symbol_hits": chunk.get("symbol_hits", 0),
        })

    return {
        "question": question,
        "suggestion": suggestion,
        "confidence": confidence["level"],
        "confidence_reason": confidence.get("reason", ""),
        "sources": sources,
        "timings": timings
    }


# ===== SSE 串流端點 =====

@app.get("/suggest/stream")
async def suggest_stream(
    question: str = Query(..., description="使用者問題"),
    top_k: int = Query(5, ge=1, le=20),
    use_hybrid: bool = Query(True, description="是否使用混合檢索")
):
    """SSE 串流端點：逐階段回傳狀態 + token + 完整結果"""

    async def generate():
        import os
        import httpx
        import time
        import json

        from ..core.hybrid_search import hybrid_search
        from ..core.confidence_evaluator import evaluate_confidence
        from ..core.prompt_builder import build_prompt
        from ..core.generate_coding_suggestion import (
            NIM_API_KEY, NIM_GENERATE_MODEL, NIM_GENERATE_URL
        )

        def sse(data: dict) -> str:
            return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

        start_total = time.perf_counter()
        timings = {}

        # 階段 1：Hybrid Search
        yield sse({"stage": "search", "message": "檢索相關程式碼...", "progress": 10})
        t0 = time.perf_counter()
        raw_results = hybrid_search(question, top_k=top_k * 3)
        timings['hybrid_search_ms'] = (time.perf_counter() - t0) * 1000
        yield sse({"stage": "search_done", "count": len(raw_results), "progress": 30})

        # 階段 2：Confidence
        yield sse({"stage": "confidence", "message": "評估信心等級...", "progress": 40})
        t0 = time.perf_counter()
        confidence = evaluate_confidence(raw_results[:top_k])
        timings['confidence_eval_ms'] = (time.perf_counter() - t0) * 1000
        yield sse({"stage": "confidence_done", "confidence": confidence["level"], "progress": 50})

        # 階段 3：Prompt Build
        yield sse({"stage": "prompt", "message": "建構提示詞...", "progress": 60})
        t0 = time.perf_counter()
        prompt = build_prompt(question, raw_results[:top_k], top_k=top_k)
        timings['prompt_build_ms'] = (time.perf_counter() - t0) * 1000
        yield sse({"stage": "prompt_done", "progress": 70})

        # 階段 4：LLM Generate (streaming)
        yield sse({"stage": "generate", "message": "生成回答中...", "progress": 80})
        t0 = time.perf_counter()

        headers = {
            "Authorization": f"Bearer {os.getenv('NIM_API_KEY')}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "nvidia/nemotron-3-ultra-550b-a55b",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 4096,
            "stream": True,
        }

        full_suggestion = ""
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", "https://integrate.api.nvidia.com/v1/chat/completions", headers=headers, json=payload) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                            delta_obj = chunk["choices"][0]["delta"]
                            # NIM streaming: 先有 reasoning_content，後有 content
                            delta = delta_obj.get("content") or delta_obj.get("reasoning_content", "")
                            if delta:
                                full_suggestion += delta
                                yield sse({"stage": "token", "token": delta})
                        except (json.JSONDecodeError, KeyError, IndexError) as e:
                            # Log parse error but continue streaming
                            print(f"  [SSE parse warning] {e}: {data[:100]}")
                            continue

        timings['llm_generate_ms'] = (time.perf_counter() - t0) * 1000
        timings['total_ms'] = (time.perf_counter() - start_total) * 1000

        # 組裝 sources（用已取得的 raw_results，避免重跑完整 pipeline）
        sources = []
        for i, chunk in enumerate(raw_results[:top_k], 1):
            sources.append({
                "source_id": i,
                "file_path": chunk.get("file_path", ""),
                "chunk_index": chunk.get("chunk_index", 0),
                "preview": chunk.get("content", "")[:200] + ("..." if len(chunk.get("content", "")) > 200 else ""),
                "rrf_score": chunk.get("rrf_score", 0.0),
                "symbol_hits": chunk.get("symbol_hits", 0),
            })

        final = {
            'stage': 'complete',
            'suggestion': full_suggestion,
            'confidence': confidence["level"],
            'confidence_reason': confidence.get("reason", ""),
            'sources': sources,
            'timings': timings,
        }
        yield sse(final)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@app.get("/health")
def health():
    return {"status": "ok", "service": "gitlab-rag-mvp"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)