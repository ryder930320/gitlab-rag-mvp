#!/usr/bin/env python3
"""CP-10 vs CP-12 對比測試"""
import httpx
import chromadb
from dotenv import load_dotenv
import os
import sys

load_dotenv()
NIM_API_KEY = os.getenv('NIM_API_KEY')
NIM_EMBED_MODEL = os.getenv('NIM_EMBED_MODEL')
NIM_EMBED_URL = 'https://integrate.api.nvidia.com/v1/embeddings'
CHROMA_DIR = 'chroma_db'
COLLECTION_NAME = 'gitlab_rag'

sys.path.insert(0, 'C:/Users/YuchiPan/hermes-workspace/gitlab-rag-mvp')
from .hybrid_search import _load_bm25_index, _min_max_normalize, _char_ngrams, _build_char_ngram_bm25
from .symbol_expansion import extract_symbol_tokens, symbol_token_bonus

# CP-10 的 QUERY_EXPANSION 字典
QUERY_EXPANSION = {
    '推論': ['infer', 'inference', 'infer_base', 'AI_Core', 'Infer'],
    '引擎': ['engine', 'infer', 'inference', 'openvino', 'Core'],
    '裝置': ['device', 'AUTO', 'CPU', 'GPU', 'available_devices'],
    '設定': ['config', 'setting', 'device', 'infer_device', 'Model_Dir'],
    '建立': ['build', 'setup', 'create', 'bdist_wheel', 'build_ext'],
    '安裝包': ['wheel', 'whl', 'package', 'dist', 'bdist_wheel'],
    '打包': ['build', 'setup', 'cython', 'cythonize', 'pyd'],
    'GPIO': ['gpio', 'DIO', 'EApiGPIO', 'device_controll', 'pin', 'set_dio_status'],
    '控制': ['control', 'controll', 'set', 'get', 'status', 'high', 'low'],
    '危險區域': ['hazard', 'hazard_analysis', 'danger', 'zone', 'polygon', 'region'],
    '偵測': ['detect', 'detection', 'analysis_obj', 'disting_obj'],
    '專案': ['project', 'Aaeon_ai_sdk', 'setup.py'],
    '如何': ['how', 'run', 'execute', 'python'],
    '步驟': ['step', 'run', 'build', 'install'],
}

def expand_query(query: str) -> str:
    expanded_terms = [query]
    for zh_term, en_terms in QUERY_EXPANSION.items():
        if zh_term in query:
            expanded_terms.extend(en_terms)
    seen = set()
    result = []
    for term in expanded_terms:
        if term not in seen:
            seen.add(term)
            result.append(term)
    return ' '.join(result)

def _embed_query(text: str):
    headers = {'Authorization': f'Bearer {NIM_API_KEY}', 'Content-Type': 'application/json'}
    payload = {'model': NIM_EMBED_MODEL, 'input': text, 'encoding_format': 'float', 'input_type': 'query'}
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(NIM_EMBED_URL, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()['data'][0]['embedding']

# CP-10 混合檢索（帶 QUERY_EXPANSION）
def hybrid_search_cp10(question: str, top_k: int = 5, alpha: float = 0.5):
    index_data = _load_bm25_index()
    chunks = index_data['chunks']
    bm25 = _build_char_ngram_bm25(chunks)
    
    expanded_query = expand_query(question)
    query_tokens = _char_ngrams(expanded_query, n=3)
    
    candidate_k = top_k * 3
    query_embedding = _embed_query(question)
    
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    collection = client.get_collection(COLLECTION_NAME)
    
    vec_results = collection.query(
        query_embeddings=[query_embedding],
        n_results=candidate_k,
        include=['documents', 'metadatas', 'distances']
    )
    
    vec_candidates = []
    for i in range(len(vec_results['ids'][0])):
        meta = vec_results['metadatas'][0][i]
        vec_candidates.append({
            'chunk_id': vec_results['ids'][0][i],
            'content': vec_results['documents'][0][i],
            'file_path': meta.get('file_path', ''),
            'source_type': meta.get('source_type', ''),
            'language': meta.get('language', ''),
            'chunk_index': meta.get('chunk_index', 0),
            'created_at': meta.get('created_at', ''),
            'score_vector': 1.0 - vec_results['distances'][0][i],
            'symbols': meta.get('symbols', [])
        })
    
    bm25_scores = bm25.get_scores(query_tokens)
    bm25_top_indices = sorted(range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True)[:candidate_k]
    
    bm25_candidates = []
    for idx in bm25_top_indices:
        chunk = chunks[idx]
        meta = chunk['metadata']
        bm25_candidates.append({
            'chunk_id': meta.get('global_chunk_id', idx),
            'content': chunk['content'],
            'file_path': meta.get('file_path', ''),
            'source_type': meta.get('source_type', ''),
            'language': meta.get('language', ''),
            'chunk_index': meta.get('chunk_index', 0),
            'created_at': meta.get('created_at', ''),
            'score_bm25': bm25_scores[idx],
            'symbols': meta.get('symbols', [])
        })
    
    all_candidates = {}
    for c in vec_candidates:
        cid = str(c['chunk_id'])
        if cid not in all_candidates:
            all_candidates[cid] = c
        else:
            all_candidates[cid]['score_vector'] = max(all_candidates[cid]['score_vector'], c['score_vector'])
    
    for c in bm25_candidates:
        cid = str(c['chunk_id'])
        if cid not in all_candidates:
            all_candidates[cid] = c
            all_candidates[cid]['score_vector'] = 0.0
        else:
            all_candidates[cid]['score_bm25'] = c['score_bm25']
    
    for c in all_candidates.values():
        c.setdefault('score_vector', 0.0)
        c.setdefault('score_bm25', 0.0)
    
    cand_list = list(all_candidates.values())
    vec_scores = [c['score_vector'] for c in cand_list]
    bm25_scores_list = [c['score_bm25'] for c in cand_list]
    
    norm_vec = _min_max_normalize(vec_scores)
    norm_bm25 = _min_max_normalize(bm25_scores_list)
    
    for i, c in enumerate(cand_list):
        c['norm_score_vector'] = norm_vec[i]
        c['norm_score_bm25'] = norm_bm25[i]
        c['symbol_bonus'] = symbol_token_bonus(question, set(extract_symbol_tokens(c.get('symbols', []))))
        c['final_score'] = alpha * c['norm_score_vector'] + (1 - alpha) * c['norm_score_bm25'] + c['symbol_bonus']
    
    cand_list.sort(key=lambda x: x['final_score'], reverse=True)
    results = cand_list[:top_k]
    
    output = []
    for r in results:
        output.append({
            'content': r['content'],
            'file_path': r['file_path'],
            'source_type': r['source_type'],
            'language': r.get('language', ''),
            'chunk_index': r.get('chunk_index', 0),
            'created_at': r.get('created_at', ''),
            'score': r['final_score'],
            'score_vector': r['score_vector'],
            'score_bm25': r['score_bm25'],
            'norm_score_vector': r.get('norm_score_vector', 0),
            'norm_score_bm25': r.get('norm_score_bm25', 0),
            'symbol_bonus': r.get('symbol_bonus', 0),
        })
    return output

# CP-12 版本
from .hybrid_search import hybrid_search

# 執行對比
test_questions = [
    '專案使用什麼推論引擎？怎麼設定裝置？',
    '如何建立 whl 安裝包？',
    'GPIO 如何控制？',
    '危險區域偵測怎麼做？',
    '專案如何打包？',
]

print('=== CP-10 (有 QUERY_EXPANSION) vs CP-12 (符號自動映射) 對比 ===')
for q in test_questions:
    r10 = hybrid_search_cp10(q, top_k=1, alpha=0.5)[0]
    r12 = hybrid_search(q, top_k=1, alpha=0.5)[0]
    print(f'\nQ: {q}')
    print(f'  CP-10: score={r10["score"]:.4f} | bonus={r10["symbol_bonus"]:.2f} | file={r10["file_path"]} | chunk#{r10["chunk_index"]}')
    print(f'  CP-12: score={r12["score"]:.4f} | bonus={r12["symbol_bonus"]:.2f} | file={r12["file_path"]} | chunk#{r12["chunk_index"]}')
    print(f'  差異: Δscore={r12["score"] - r10["score"]:+.4f}')