#!/usr/bin/env python3
"""
Ad-hoc verification for CP-16~20 changed files:
- confidence_evaluator.py
- hybrid_search.py
- prompt_builder.py
- rag_interface.py
"""
import sys
import traceback

def test_imports():
    """Test all imports work with relative imports"""
    try:
        from gitlab_rag.confidence_evaluator import evaluate_confidence
        from gitlab_rag.hybrid_search import hybrid_search
        from gitlab_rag.prompt_builder import build_prompt
        from gitlab_rag.rag_interface import query_gitlab_context, get_coding_suggestion
        print("✅ Imports: all 4 modules import successfully")
        return True
    except Exception as e:
        print(f"❌ Imports failed: {e}")
        traceback.print_exc()
        return False

def test_confidence_evaluator():
    """Test confidence evaluator logic"""
    try:
        from gitlab_rag.hybrid_search import hybrid_search
        from gitlab_rag.confidence_evaluator import evaluate_confidence
        
        # High confidence case (known working query)
        results = hybrid_search('GPIO 控制怎麼用？', top_k=3)
        conf = evaluate_confidence(results)
        assert conf['level'] == 'high', f"Expected high, got {conf['level']}"
        assert '33.0%' in conf['reason'] or '差距' in conf['reason'], "Reason should mention gap"
        print(f"✅ confidence_evaluator: {conf['level']} - {conf['reason'][:60]}")
        
        # Medium confidence case
        results2 = hybrid_search('建立 whl 安裝包', top_k=3)
        conf2 = evaluate_confidence(results2)
        assert conf2['level'] in ('medium', 'low'), f"Expected medium/low, got {conf2['level']}"
        print(f"✅ confidence_evaluator (whl): {conf2['level']}")
        return True
    except Exception as e:
        print(f"❌ confidence_evaluator test failed: {e}")
        traceback.print_exc()
        return False

def test_hybrid_search():
    """Test hybrid search returns valid structure"""
    try:
        from gitlab_rag.hybrid_search import hybrid_search
        results = hybrid_search('GPIO 控制怎麼用？', top_k=3)
        assert len(results) == 3, f"Expected 3 results, got {len(results)}"
        for r in results:
            assert 'file_path' in r
            assert 'chunk_index' in r
            assert 'rrf_score' in r
            assert 'symbol_hits' in r
            assert 'vec_rank' in r
            assert 'bm25_rank' in r
        print(f"✅ hybrid_search: {len(results)} results with correct schema")
        return True
    except Exception as e:
        print(f"❌ hybrid_search test failed: {e}")
        traceback.print_exc()
        return False

def test_prompt_builder():
    """Test prompt builder produces valid prompt"""
    try:
        from gitlab_rag.hybrid_search import hybrid_search
        from gitlab_rag.prompt_builder import build_prompt
        
        results = hybrid_search('GPIO 控制怎麼用？', top_k=3)
        prompt = build_prompt('GPIO 控制怎麼用？', results)
        
        assert len(prompt) > 100, "Prompt should be substantial"
        assert '來源 1' in prompt, "Should contain source markers"
        assert '來源 2' in prompt
        assert '回答指示' in prompt, "Should contain instructions"
        assert '不得捏造' in prompt or '不可捏造' in prompt, "Should contain anti-hallucination instruction"
        print(f"✅ prompt_builder: {len(prompt)} chars, contains required elements")
        return True
    except Exception as e:
        print(f"❌ prompt_builder test failed: {e}")
        traceback.print_exc()
        return False

def test_rag_interface():
    """Test rag_interface public API"""
    try:
        from gitlab_rag.rag_interface import query_gitlab_context, get_coding_suggestion
        
        # Test query_gitlab_context
        results = query_gitlab_context('GPIO 控制怎麼用？', top_k=3)
        assert len(results) == 3
        for r in results:
            assert 'file_path' in r
            assert 'rrf_score' in r
        print(f"✅ query_gitlab_context: {len(results)} results")
        
        # Test get_coding_suggestion
        sug = get_coding_suggestion('GPIO 控制怎麼用？', top_k=3)
        assert 'suggestion' in sug
        assert 'confidence' in sug
        assert 'confidence_reason' in sug
        assert 'sources' in sug
        assert sug['confidence'] == 'high'
        print(f"✅ get_coding_suggestion: confidence={sug['confidence']}, sources={len(sug['sources'])}")
        return True
    except Exception as e:
        print(f"❌ rag_interface test failed: {e}")
        traceback.print_exc()
        return False

def test_fastapi_endpoints():
    """Test FastAPI endpoints via TestClient"""
    try:
        from gitlab_rag.app import app
        from fastapi.testclient import TestClient
        
        client = TestClient(app)
        
        # GET /query
        r = client.get('/query?question=GPIO%20%E6%8E%A7%E5%88%B6%E6%80%8E%E9%BA%BC%E7%94%A8%EF%BC%9F&top_k=3')
        assert r.status_code == 200
        data = r.json()
        assert data['count'] == 3
        print(f"✅ GET /query: {data['count']} results")
        
        # GET /suggest
        r = client.get('/suggest?question=GPIO%20%E6%8E%A7%E5%88%B6%E6%80%8E%E9%BA%BC%E7%94%A8%EF%BC%9F&top_k=3')
        assert r.status_code == 200
        data = r.json()
        assert data['confidence'] == 'high'
        print(f"✅ GET /suggest: confidence={data['confidence']}")
        
        # POST /query
        r = client.post('/query', json={'question': 'GPIO 控制怎麼用？', 'top_k': 3})
        assert r.status_code == 200
        print(f"✅ POST /query: {r.json()['count']} results")
        
        # POST /suggest
        r = client.post('/suggest', json={'question': 'GPIO 控制怎麼用？', 'top_k': 3})
        assert r.status_code == 200
        print(f"✅ POST /suggest: confidence={r.json()['confidence']}")
        return True
    except Exception as e:
        print(f"❌ FastAPI endpoints test failed: {e}")
        traceback.print_exc()
        return False

def main():
    print("=" * 60)
    print("HERMES VERIFICATION: CP-16~20 Changed Files")
    print("=" * 60)
    
    tests = [
        ("Imports", test_imports),
        ("Confidence Evaluator", test_confidence_evaluator),
        ("Hybrid Search", test_hybrid_search),
        ("Prompt Builder", test_prompt_builder),
        ("RAG Interface", test_rag_interface),
        ("FastAPI Endpoints", test_fastapi_endpoints),
    ]
    
    passed = 0
    failed = 0
    for name, test_fn in tests:
        print(f"\n--- {name} ---")
        try:
            if test_fn():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ {name} crashed: {e}")
            traceback.print_exc()
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"SUMMARY: {passed}/{passed+failed} tests passed")
    if failed == 0:
        print("✅ ALL VERIFICATIONS PASSED")
        return 0
    else:
        print(f"❌ {failed} TEST(S) FAILED")
        return 1

if __name__ == '__main__':
    sys.exit(main())
