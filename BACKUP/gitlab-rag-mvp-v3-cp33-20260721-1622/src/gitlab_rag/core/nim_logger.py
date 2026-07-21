#!/usr/bin/env python3
"""
NIM API 呼叫持久化記錄模組 (CP-26)
- SQLite + JSONL 雙重存儲
- 支援 embedding / rerank / generate / evaluate_faithfulness 四種呼叫類型
- 記錄：timestamp, query, model, call_type, request/response payload, fallback_flag, latency_ms, status_code, error
"""
import os
import json
import sqlite3
import time
import threading
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
from contextlib import contextmanager

# 使用 BASE_DIR 解決相對路徑問題
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
DB_PATH = str(BASE_DIR / "data" / "nim_calls.db")
JSONL_PATH = str(BASE_DIR / "data" / "nim_calls.jsonl")

# 確保資料目錄存在
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
Path(JSONL_PATH).parent.mkdir(parents=True, exist_ok=True)

# 線程安全的資料庫連線
_thread_local = threading.local()
_init_lock = threading.Lock()
_initialized = False


def _get_db_conn():
    """取得線程本地的 SQLite 連線"""
    if not hasattr(_thread_local, 'conn') or _thread_local.conn is None:
        _thread_local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _thread_local.conn.row_factory = sqlite3.Row
    return _thread_local.conn


def _clear_thread_local_conns():
    """清除所有 thread-local 緩存的連線（schema 變更後呼叫）"""
    if hasattr(_thread_local, 'conn') and _thread_local.conn is not None:
        try:
            _thread_local.conn.close()
        except Exception:
            pass
        _thread_local.conn = None


def _ensure_schema_migration():
    """檢查並補上缺失欄位（僅在首次初始化時執行一次）"""
    conn = _get_db_conn()
    cursor = conn.execute("PRAGMA table_info(nim_calls)")
    columns = [row[1] for row in cursor.fetchall()]
    
    if 'response_headers' not in columns:
        print("  🔧 Schema migration: adding response_headers column...")
        conn.execute("ALTER TABLE nim_calls ADD COLUMN response_headers TEXT")
        conn.commit()
        # schema 變更後清除 thread-local 連線緩存
        _clear_thread_local_conns()


def init_db():
    """初始化資料庫表結構（線程安全，冪等）"""
    global _initialized
    with _init_lock:
        if _initialized:
            return
        conn = _get_db_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS nim_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,          -- ISO 8601
                query TEXT,                       -- 原始查詢（可能為空）
                model TEXT NOT NULL,              -- 使用的模型名稱
                call_type TEXT NOT NULL,          -- embedding / rerank / generate / evaluate_faithfulness
                request_payload TEXT,             -- JSON 字串
                response_payload TEXT,            -- JSON 字串
                response_headers TEXT,            -- JSON 字串：關鍵 header（Retry-After, X-RateLimit-*）
                fallback_triggered INTEGER DEFAULT 0,  -- 是否觸發 fallback（重試/降級）
                latency_ms INTEGER,               -- 端到端延遲（毫秒）
                status_code INTEGER,              -- HTTP 狀態碼
                error TEXT                        -- 錯誤訊息（若有）
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_nim_calls_timestamp ON nim_calls(timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_nim_calls_call_type ON nim_calls(call_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_nim_calls_model ON nim_calls(model)")
        conn.commit()
        
        # 執行 schema migration（補上 response_headers）
        _ensure_schema_migration()
        
        _initialized = True


@contextmanager
def _jsonl_append():
    """安全追加寫入 JSONL"""
    try:
        with open(JSONL_PATH, 'a', encoding='utf-8') as f:
            yield f
    except Exception:
        pass  # JSONL 寫入失敗不影響主流程


def log_nim_call(
    call_type: str,
    model: str,
    request_payload: Dict[str, Any],
    response_payload: Optional[Dict[str, Any]] = None,
    query: str = "",
    fallback_triggered: bool = False,
    latency_ms: int = 0,
    status_code: int = 200,
    error: str = "",
    response_headers: Optional[Dict[str, str]] = None
):
    """
    記錄 NIM API 呼叫（SQLite + JSONL 雙寫）

    Args:
        call_type: embedding / rerank / generate / evaluate_faithfulness
        model: 模型名稱（如 nvidia/nv-embedqa-e5-v5）
        request_payload: 發送的請求 payload
        response_payload: 收到的回應 payload（可為 None）
        query: 原始使用者查詢（用於關聯）
        fallback_triggered: 是否觸發了重試/降級邏輯
        latency_ms: 端到端延遲（毫秒）
        status_code: HTTP 狀態碼
        error: 錯誤訊息（若有）
        response_headers: 回應的 HTTP headers（過濾記錄 rate/retry/limit 相關）
    """
    init_db()

    timestamp = datetime.utcnow().isoformat() + 'Z'

    # 過濾關鍵 header（rate/retry/limit 相關）
    filtered_headers = {}
    if response_headers:
        for k, v in response_headers.items():
            kl = k.lower()
            if any(key in kl for key in ('rate', 'retry', 'limit', 'reset')):
                filtered_headers[k] = v

    # SQLite 寫入
    try:
        conn = _get_db_conn()
        conn.execute(
            """INSERT INTO nim_calls
               (timestamp, query, model, call_type, request_payload, response_payload,
                response_headers, fallback_triggered, latency_ms, status_code, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                timestamp,
                query,
                model,
                call_type,
                json.dumps(request_payload, ensure_ascii=False),
                json.dumps(response_payload, ensure_ascii=False) if response_payload else None,
                json.dumps(filtered_headers, ensure_ascii=False) if filtered_headers else None,
                1 if fallback_triggered else 0,
                latency_ms,
                status_code,
                error
            )
        )
        conn.commit()
    except Exception as e:
        # 資料庫寫入失敗不影響主流程，但打印警告
        print(f"  ⚠️  nim_logger SQLite 寫入失敗: {e}")

    # JSONL 寫入（追加模式，適合串流分析）
    try:
        record = {
            "timestamp": timestamp,
            "query": query,
            "model": model,
            "call_type": call_type,
            "request_payload": request_payload,
            "response_payload": response_payload,
            "response_headers": filtered_headers if filtered_headers else None,
            "fallback_triggered": fallback_triggered,
            "latency_ms": latency_ms,
            "status_code": status_code,
            "error": error
        }
        with _jsonl_append() as f:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')
    except Exception as e:
        print(f"  ⚠️  nim_logger JSONL 寫入失敗: {e}")


def get_recent_calls(limit: int = 100, call_type: Optional[str] = None) -> list:
    """查詢最近的呼叫記錄（供除錯/分析用）"""
    init_db()
    conn = _get_db_conn()
    if call_type:
        rows = conn.execute(
            "SELECT * FROM nim_calls WHERE call_type = ? ORDER BY id DESC LIMIT ?",
            (call_type, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM nim_calls ORDER BY id DESC LIMIT ?",
            (limit,)
        ).fetchall()
    return [dict(row) for row in rows]


def get_call_stats() -> Dict[str, Any]:
    """取得呼叫統計摘要"""
    init_db()
    conn = _get_db_conn()

    total = conn.execute("SELECT COUNT(*) FROM nim_calls").fetchone()[0]

    by_type = dict(conn.execute(
        "SELECT call_type, COUNT(*) FROM nim_calls GROUP BY call_type"
    ).fetchall())

    by_status = dict(conn.execute(
        "SELECT status_code, COUNT(*) FROM nim_calls GROUP BY status_code"
    ).fetchall())

    fallback_count = conn.execute(
        "SELECT COUNT(*) FROM nim_calls WHERE fallback_triggered = 1"
    ).fetchone()[0]

    avg_latency = conn.execute(
        "SELECT AVG(latency_ms) FROM nim_calls WHERE latency_ms > 0"
    ).fetchone()[0]

    return {
        "total_calls": total,
        "by_type": by_type,
        "by_status_code": by_status,
        "fallback_triggered_count": fallback_count,
        "avg_latency_ms": round(avg_latency, 1) if avg_latency else 0
    }


if __name__ == "__main__":
    # 簡單測試
    init_db()
    log_nim_call(
        call_type="embedding",
        model="nvidia/nv-embedqa-e5-v5",
        request_payload={"model": "nvidia/nv-embedqa-e5-v5", "input": "test", "input_type": "query"},
        response_payload={"data": [{"embedding": [0.1] * 1024}]},
        query="test query",
        latency_ms=150,
        status_code=200
    )
    print("Stats:", get_call_stats())
    print("Recent:", get_recent_calls(5))