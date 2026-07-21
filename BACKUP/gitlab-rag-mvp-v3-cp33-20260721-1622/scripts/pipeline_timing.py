#!/usr/bin/env python3
"""
RAG Pipeline 階段延遲追蹤器
可直接呼叫或整合到既有流程
"""
import os
import sys
import time
import httpx
import chromadb
from dotenv import load_dotenv
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from contextlib import contextmanager

# 將專案根目錄加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

NIM_API_KEY = os.getenv("NIM_API_KEY")
NIM_EMBED_MODEL = os.getenv("NIM_EMBED_MODEL")
NIM_EMBED_URL = "https://integrate.api.nvidia.com/v1/embeddings"
NIM_GENERATE_MODEL = os.getenv("NIM_GENERATE_MODEL", "nvidia/nemotron-3-ultra-550b-a55b")
NIM_GENERATE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

CHROMA_DIR = "chroma_db"
COLLECTION_NAME = "gitlab_rag"

# 全域連線池
_client = None
_collection = None

def _get_collection():
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(path=CHROMA_DIR)
        _collection = _client.get_collection(COLLECTION_NAME)
    return _collection


@dataclass
class StageTiming:
    name: str
    start: float = 0
    end: float = 0
    metadata: Dict = field(default_factory=dict)
    
    @property
    def duration_ms(self) -> float:
        return (self.end - self.start) * 1000


@dataclass
class PipelineTimings:
    stages: List[StageTiming] = field(default_factory=list)
    
    def add(self, name: str, metadata: Dict = None) -> StageTiming:
        stage = StageTiming(name=name, metadata=metadata or {})
        self.stages.append(stage)
        return stage
    
    def print_summary(self):
        print("\n" + "="*70)
        print("RAG PIPELINE 階段延遲分析")
        print("="*70)
        total = sum(s.duration_ms for s in self.stages)
        print(f"{'階段':<30} {'耗時(ms)':>10} {'佔比':>8} {'備註'}")
        print("-"*70)
        for s in self.stages:
            pct = (s.duration_ms / total * 100) if total > 0 else 0
            meta = " ".join(f"{k}={v}" for k,v in s.metadata.items())
            print(f"{s.name:<30} {s.duration_ms:>10.1f} {pct:>7.1f}%  {meta}")
        print("-"*70)
        print(f"{'總計':<30} {total:>10.1f} {'100.0%':>8}")
        print("="*70)


class TimedPipeline:
    """帶延遲追蹤的 RAG Pipeline"""
    
    def __init__(self):
        self.timings = PipelineTimings()
    
    @contextmanager
    def stage(self, name: str, **metadata):
        """Context manager 自動計時"""
        stage = self.timings.add(name, metadata)
        stage.start = time.perf_counter()
        try:
            yield stage
        finally:
            stage.end = time.perf_counter()
    
    def print_timings(self):
        self.timings.print_summary()
    
    # ===== 各階段實作 =====
    
    def expand_query(self, question: str) -> str:
        """階段 1：查詢擴展（中文→英文技術詞）"""
        with self.stage("query_expand", original_len=len(question)) as st:
            # 這裡接你的 query_expander.py 邏輯
            # 暫時直接返回原查詢
            expanded = question
            st.metadata["expanded_len"] = len(expanded)
        return expanded
    
    def generate_embedding(self, text: str) -> List[float]:
        """階段 2：Embedding 生成"""
        with self.stage("embedding", model=NIM_EMBED_MODEL, input_len=len(text)) as st:
            headers = {
                "Authorization": f"Bearer {NIM_API_KEY}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": NIM_EMBED_MODEL,
                "input": text,
                "encoding_format": "float",
                "input_type": "query"
            }
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(NIM_EMBED_URL, headers=headers, json=payload)
                resp.raise_for_status()
                embedding = resp.json()["data"][0]["embedding"]
            st.metadata["dim"] = len(embedding)
        return embedding
    
    def vector_search(self, embedding: List[float], top_k: int) -> List[Dict]:
        """階段 3：向量檢索"""
        with self.stage("vector_search", top_k=top_k) as st:
            collection = _get_collection()
            results = collection.query(
                query_embeddings=[embedding],
                n_results=top_k,
                include=["documents", "metadatas", "distances"]
            )
            hits = []
            for i in range(len(results["ids"][0])):
                meta = results["metadatas"][0][i]
                hits.append({
                    "content": results["documents"][0][i],
                    "file_path": meta.get("file_path", ""),
                    "source_type": meta.get("source_type", ""),
                    "language": meta.get("language", ""),
                    "chunk_index": meta.get("chunk_index", 0),
                    "created_at": meta.get("created_at", ""),
                    "score": 1.0 - results["distances"][0][i],
                })
            st.metadata["results"] = len(hits)
        return hits
    
    def bm25_search(self, question: str, top_k: int) -> List[Dict]:
        """階段 4：BM25 檢索（需 hybrid_search.py）"""
        with self.stage("bm25_search", top_k=top_k) as st:
            from src.gitlab_rag.core.hybrid_search import hybrid_search
            raw = hybrid_search(question, top_k=top_k)
            # hybrid_search 內部已含 BM25+Vector+Symbol+RRF
            # 這裡只計時整體
            st.metadata["raw_results"] = len(raw)
        return raw
    
    def rerank(self, question: str, candidates: List[Dict], top_k: int) -> List[Dict]:
        """階段 5：Reranking（nemotron-3-ultra） - 這裡直接使用 hybrid_search 的 RRF 結果"""
        with self.stage("rerank", candidates=len(candidates), top_k=top_k) as st:
            # hybrid_search 內部已包含 RRF 融合，這裡只做 top_k 截斷
            ranked = candidates[:top_k]
            st.metadata["reranked"] = len(ranked)
        return ranked
    
    def evaluate_confidence(self, chunks: List[Dict]) -> Dict:
        """階段 6：信心評估"""
        with self.stage("confidence_eval", chunks=len(chunks)) as st:
            from src.gitlab_rag.core.confidence_evaluator import evaluate_confidence
            conf = evaluate_confidence(chunks)
            st.metadata["level"] = conf["level"]
            st.metadata["score"] = conf.get("score", 0)
        return conf
    
    def build_prompt(self, question: str, chunks: List[Dict], top_k: int) -> str:
        """階段 7：Prompt 建構"""
        with self.stage("prompt_build", question_len=len(question), chunks=len(chunks)) as st:
            from src.gitlab_rag.core.prompt_builder import build_prompt
            prompt = build_prompt(question, chunks, top_k=top_k)
            st.metadata["prompt_len"] = len(prompt)
        return prompt
    
    def generate(self, prompt: str, timeout: float = 60.0) -> str:
        """階段 8：LLM 生成"""
        with self.stage("llm_generate", model=NIM_GENERATE_MODEL, prompt_len=len(prompt)) as st:
            headers = {
                "Authorization": f"Bearer {NIM_API_KEY}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": NIM_GENERATE_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 4096,
                "stream": False,
            }
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(NIM_GENERATE_URL, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"].strip()
                finish_reason = data["choices"][0].get("finish_reason")
                usage = data.get("usage", {})
            st.metadata["finish_reason"] = finish_reason
            st.metadata["completion_tokens"] = usage.get("completion_tokens", 0)
            st.metadata["prompt_tokens"] = usage.get("prompt_tokens", 0)
        return content
    
    # ===== 完整流程 =====
    
    def query_with_timing(self, question: str, top_k: int = 5, use_hybrid: bool = True) -> Dict:
        """執行完整查詢並回傳結果 + 完整延遲資訊"""
        self.timings = PipelineTimings()  # 重置
        
        try:
            # 1. Query expand
            expanded = self.expand_query(question)
            
            # 2. Embedding
            embedding = self.generate_embedding(expanded)
            
            # 3. Hybrid search (含 vector + BM25 + symbol + RRF)
            if use_hybrid:
                raw_results = self.bm25_search(expanded, top_k * 3)
                # Rerank
                reranked = self.rerank(expanded, raw_results, top_k)
                final_chunks = reranked
            else:
                final_chunks = self.vector_search(embedding, top_k)
            
            # 4. Confidence
            confidence = self.evaluate_confidence(final_chunks)
            
            # 5. Prompt
            prompt = self.build_prompt(expanded, final_chunks, top_k)
            
            # 6. Generate
            suggestion = self.generate(prompt)
            
            return {
                "question": question,
                "suggestion": suggestion,
                "confidence": confidence["level"],
                "confidence_reason": confidence.get("reason", ""),
                "sources": [{
                    "file_path": c["file_path"],
                    "chunk_index": c["chunk_index"],
                    "preview": c["content"][:200]
                } for c in final_chunks[:top_k]],
                "timings": self.timings
            }
        except Exception as e:
            return {
                "error": str(e),
                "timings": self.timings
            }


def main():
    """CLI 測試：單次查詢並顯示完整延遲"""
    import sys
    
    question = sys.argv[1] if len(sys.argv) > 1 else "GPIO 控制怎麼用？"
    top_k = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    
    print(f"查詢：{question}")
    print(f"Top-K：{top_k}")
    print("執行中...\n")
    
    pipeline = TimedPipeline()
    result = pipeline.query_with_timing(question, top_k=top_k)
    
    if "error" in result:
        print(f"錯誤：{result['error']}")
    else:
        print(f"\n信心等級：{result['confidence']}")
        print(f"理由：{result['confidence_reason']}")
        print(f"\n建議內容：\n{result['suggestion'][:500]}...")
        print(f"\n引用來源：{len(result['sources'])} 筆")
    
    # 顯示延遲分析
    result["timings"].print_summary()


if __name__ == "__main__":
    main()