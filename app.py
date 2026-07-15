"""FastAPI wrapper for GitLab RAG - HTTP endpoint for Hermes (MVP 版本：純向量檢索)"""
from fastapi import FastAPI, Query
from pydantic import BaseModel
from typing import List

from rag_interface import query_gitlab_context, format_results

app = FastAPI(title="GitLab RAG MVP", version="0.1.0")


class QueryRequest(BaseModel):
    question: str
    top_k: int = 5


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
    top_k: int = Query(5, ge=1, le=20)
):
    """GET 端點：/query?question=xxx&top_k=5"""
    hits = query_gitlab_context(question, top_k=top_k)
    return QueryResponse(
        question=question,
        results=[Hit(**h) for h in hits],
        count=len(hits)
    )


@app.post("/query", response_model=QueryResponse)
def query_post(req: QueryRequest):
    """POST 端點：/query {question, top_k}"""
    hits = query_gitlab_context(req.question, top_k=req.top_k)
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