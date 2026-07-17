"""NIM API 呼叫持久化日誌 (CP-26)

記錄所有對 NIM API 的呼叫：
- embedding (向量化)
- rerank (重排序) 
- generate (生成建議)

每筆記錄包含：
- timestamp: ISO 8601
- query: 原始查詢字串
- model: 模型名稱
- call_type: "embedding" | "rerank" | "generate"
- request: 原始 request payload (JSON)
- response: 原始 response (JSON)，至少保留關鍵字段
- finish_reason: 生成類才有
- fallback: 是否觸發 fallback (reranker 503 回退 RRF)
- latency_ms: 耗時毫秒
- error: 錯誤資訊 (若有)
- status_code: HTTP 狀態碼
"""
import os
import json
import sqlite3
import threading
from datetime import datetime
from typing import Dict, Any, Optional
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

LOG_DB_PATH = os.getenv("NIM_LOG_DB", "data/nim_api_log.db")
LOG_JSONL_PATH = os.getenv("NIM_LOG_JSONL", "data/nim_api_log.jsonl")

# 確保目錄存在
Path(LOG_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
Path(LOG_JSONL_PATH).parent.mkdir(parents=True, exist_ok=True)

_local = threading.local()


def _get_db() -> sqlite3.Connection:
    """取得 thread-local SQLite 連線"""
    if not hasattr(_local, "conn"):
        _local.conn = sqlite3.connect(LOG_DB_PATH, check_same_thread=False)
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _init_schema(_local.conn)
    return _local.conn


def _init_schema(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS nim_api_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,           -- ISO 8601 UTC
            query TEXT NOT NULL,               -- 原始查詢
            model TEXT NOT NULL,               -- 模型名稱
            call_type TEXT NOT NULL,           -- embedding | rerank | generate
            request_json TEXT NOT NULL,        -- 完整 request payload
            response_json TEXT,                -- 完整 response (可能很大)
            finish_reason TEXT,                -- 生成類專用
            fallback INTEGER DEFAULT 0,        -- 是否觸發 fallback
            latency_ms INTEGER NOT NULL,       -- 耗時毫秒
            error TEXT,                        -- 錯誤資訊 (若有)
            status_code INTEGER,               -- HTTP 狀態碼
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_nim_log_query ON nim_api_log(query)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_nim_log_timestamp ON nim_api_log(timestamp)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_nim_log_call_type ON nim_api_log(call_type)
    """)
    conn.commit()


def log_nim_call(
    query: str,
    model: str,
    call_type: str,
    request: Optional[Dict[str, Any]] = None,
    request_payload: Optional[Dict[str, Any]] = None,
    response: Optional[Dict[str, Any]] = None,
    response_payload: Optional[Dict[str, Any]] = None,
    finish_reason: Optional[str] = None,
    fallback: bool = False,
    fallback_triggered: Optional[bool] = None,
    latency_ms: int = 0,
    error: Optional[str] = None,
    status_code: Optional[int] = None,
) -> int:
    """寫入一筆 NIM API 呼叫記錄，回傳 row id"""
    timestamp = datetime.utcnow().isoformat() + "Z"
    conn = _get_db()

    req = request_payload if request_payload is not None else request
    resp = response_payload if response_payload is not None else response
    fb = fallback_triggered if fallback_triggered is not None else fallback

    row_id = conn.execute(
        """
        INSERT INTO nim_api_log
        (timestamp, query, model, call_type, request_json, response_json,
         finish_reason, fallback, latency_ms, error, status_code)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            timestamp,
            query,
            model,
            call_type,
            json.dumps(req, ensure_ascii=False) if req else None,
            json.dumps(resp, ensure_ascii=False) if resp else None,
            finish_reason,
            1 if fb else 0,
            latency_ms,
            error,
            status_code,
        ),
    ).lastrowid
    conn.commit()

    # 同步寫 JSONL 方便 tail -f / grep
    jsonl_record = {
        "id": row_id,
        "timestamp": timestamp,
        "query": query,
        "model": model,
        "call_type": call_type,
        "request": req,
        "response": resp,
        "finish_reason": finish_reason,
        "fallback": fb,
        "latency_ms": latency_ms,
        "error": error,
        "status_code": status_code,
    }
    with open(LOG_JSONL_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(jsonl_record, ensure_ascii=False) + "\n")

    return row_id


def query_logs(
    query: Optional[str] = None,
    call_type: Optional[str] = None,
    since: Optional[str] = None,  # ISO timestamp
    limit: int = 100,
) -> list[Dict[str, Any]]:
    """查詢日誌（給人工覆核用）"""
    conn = _get_db()
    sql = "SELECT * FROM nim_api_log WHERE 1=1"
    params = []
    if query:
        sql += " AND query LIKE ?"
        params.append(f"%{query}%")
    if call_type:
        sql += " AND call_type = ?"
        params.append(call_type)
    if since:
        sql += " AND timestamp >= ?"
        params.append(since)
    sql += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    cur = conn.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_stats() -> Dict[str, Any]:
    """統計摘要"""
    conn = _get_db()
    cur = conn.execute("""
        SELECT call_type, COUNT(*) as cnt,
               AVG(latency_ms) as avg_latency,
               SUM(CASE WHEN fallback=1 THEN 1 ELSE 0 END) as fallbacks,
               SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) as errors
        FROM nim_api_log
        GROUP BY call_type
    """)
    return {row[0]: {"count": row[1], "avg_latency_ms": row[2], "fallbacks": row[3], "errors": row[4]} for row in cur.fetchall()}


def init_db():
    """手動初始化（供腳本呼叫）"""
    _get_db()
    print(f"DB initialized at {LOG_DB_PATH}")


if __name__ == "__main__":
    # 簡單測試
    log_nim_call(
        query="test query",
        model="nvidia/nv-embedqa-e5-v5",
        call_type="embedding",
        request={"model": "nvidia/nv-embedqa-e5-v5", "input": "test"},
        response={"data": [{"embedding": [0.1]*1024}]},
        latency_ms=123,
    )
    print("Test log written.")
    print(json.dumps(query_logs(limit=5), ensure_ascii=False, indent=2))
    print(json.dumps(get_stats(), ensure_ascii=False, indent=2))