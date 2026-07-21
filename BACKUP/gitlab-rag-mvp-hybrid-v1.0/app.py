"""FastAPI wrapper for GitLab RAG - HTTP endpoint for Hermes"""
from fastapi import FastAPI, Query
from pydantic import BaseModel
from typing import List, Optional

from rag_interface import query_gitlab_context, format_results

app = FastAPI(title="GitLab RAG MVP", version="0.1.0")


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


@app.get("/query", response_model=QueryResponse)
def query_get(
    question: str = Query(..., description="使用者問題"),
    top_k: int = Query(5, ge=1, le=20),
    use_hybrid: bool = Query(True, description="是否使用混合檢索（向量+BM25），False 退回純向量")
):
    """GET 端點：/query?question=xxx&top_k=5&use_hybrid=true"""
    hits = query_gitlab_context(question, top_k=top_k, use_hybrid=use_hybrid)
    return QueryResponse(
        question=question,
        results=[Hit(**h) for h in hits],
        count=len(hits)
    )


@app.post("/query", response_model=QueryResponse)
def query_post(req: QueryRequest):
    """POST 端點：/query {question, top_k, use_hybrid}"""
    hits = query_gitlab_context(req.question, top_k=req.top_k, use_hybrid=req.use_hybrid)
    return QueryResponse(
        question=req.question,
        results=[Hit(**h) for h in hits],
        count=len(hits)
    )


@app.get("/health")
def health():
    return {"status": "ok", "service": "gitlab-rag-mvp"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)