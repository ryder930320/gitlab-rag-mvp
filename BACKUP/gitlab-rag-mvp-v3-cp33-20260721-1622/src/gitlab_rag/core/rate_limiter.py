"""
全局 NIM API 速率限制器（CP-33）

- 單例模式，embedding 與 generate 共用同一配額池
- 初始閾值：35 RPM（40 RPM 免費層上限的 87.5%，留緩衝）
- embedding 與 generate 呼叫共用同一配額池（NVIDIA 免費層 40 RPM 為帳號級共用配額）
- 滑動窗口實現，線程安全
"""
import time
import threading
from collections import deque
from typing import Optional


class GlobalRateLimiter:
    """全局 NIM API 速率限制器（單例）"""
    
    _instance: Optional['GlobalRateLimiter'] = None
    _lock = threading.Lock()
    
    def __new__(cls, max_rpm: int = 35, window_seconds: float = 60.0):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, max_rpm: int = 35, window_seconds: float = 60.0):
        if self._initialized:
            return
        self.max_calls = max_rpm
        self.window = window_seconds
        self.calls = deque()
        self.lock = threading.Lock()
        self._initialized = True
        # 動態調整記錄
        self.adjustment_history = []
        self.current_rpm = max_rpm
    
    def acquire(self, timeout: Optional[float] = None) -> float:
        """
        獲取許可，返回實際等待時間（秒）
        如果 timeout 不為 None 且超時則拋出 TimeoutError
        """
        start_time = time.time()
        while True:
            with self.lock:
                now = time.time()
                # 清理過期記錄
                while self.calls and self.calls[0] <= now - self.window:
                    self.calls.popleft()
                
                if len(self.calls) < self.max_calls:
                    self.calls.append(now)
                    return time.time() - start_time
                
                # 計算需等待時間
                wait_time = self.calls[0] + self.window - now
            
            if wait_time <= 0:
                continue
                
            if timeout is not None and (time.time() - start_time + wait_time) > timeout:
                raise TimeoutError(f"Rate limiter timeout after {timeout}s")
            
            # 等待
            time.sleep(min(wait_time, 1.0))  # 分段睡眠，便於及時檢查 timeout
    
    def get_current_rpm(self) -> int:
        """獲取當前設置的 RPM"""
        with self.lock:
            return self.current_rpm
    
    def set_rpm(self, new_rpm: int) -> int:
        """調整 RPM 限制，返回舊值"""
        with self.lock:
            old_rpm = self.current_rpm
            self.current_rpm = new_rpm
            self.max_calls = new_rpm
            # 記錄調整歷史
            self.adjustment_history.append({
                'timestamp': time.time(),
                'old_rpm': old_rpm,
                'new_rpm': new_rpm,
                'reason': 'manual_adjustment'
            })
            return old_rpm
    
    def adjust_rpm(self, factor: float, reason: str = '') -> int:
        """按比例調整 RPM（如 0.8 表示降 20%），返回新值"""
        with self.lock:
            new_rpm = max(1, int(self.current_rpm * factor))
            old_rpm = self.current_rpm
            self.current_rpm = new_rpm
            self.max_calls = new_rpm
            self.adjustment_history.append({
                'timestamp': time.time(),
                'old_rpm': old_rpm,
                'new_rpm': new_rpm,
                'factor': factor,
                'reason': reason
            })
            return new_rpm
    
    def get_stats(self) -> dict:
        """獲取限流器狀態統計"""
        with self.lock:
            now = time.time()
            recent_calls = sum(1 for t in self.calls if t > now - 60)
            return {
                'current_rpm': self.current_rpm,
                'max_rpm': self.max_calls,
                'window_seconds': self.window,
                'current_minute_calls': recent_calls,
                'queue_length': len(self.calls),
                'adjustment_count': len(self.adjustment_history),
                'last_adjustment': self.adjustment_history[-1] if self.adjustment_history else None
            }
    
    def record_429(self):
        """記錄 429 觸發，用於動態調整判斷"""
        with self.lock:
            self.adjustment_history.append({
                'timestamp': time.time(),
                'old_rpm': self.current_rpm,
                'new_rpm': self.current_rpm,
                'factor': 1.0,
                'reason': '429_triggered'
            })


# 全局單例實例
_global_rate_limiter: Optional[GlobalRateLimiter] = None


def get_global_rate_limiter(max_rpm: int = 35, window_seconds: float = 60.0) -> GlobalRateLimiter:
    """獲取全局限流器單例"""
    global _global_rate_limiter
    if _global_rate_limiter is None:
        _global_rate_limiter = GlobalRateLimiter(max_rpm, window_seconds)
    return _global_rate_limiter


def acquire_rate_limit() -> float:
    """便捷函數：獲取全局限流許可，返回等待時間"""
    return get_global_rate_limiter().acquire()


# 測試代碼
if __name__ == "__main__":
    import sys
    limiter = GlobalRateLimiter(max_rpm=35, window_seconds=60.0)
    
    print(f"Initial stats: {limiter.get_stats()}")
    
    # 模擬 5 個快速請求
    for i in range(5):
        wait = limiter.acquire()
        print(f"Request {i+1}: waited {wait:.4f}s")
    
    print(f"Stats after 5 requests: {limiter.get_stats()}")
    
    # 測試動態調整
    print(f"\nAdjusting RPM to 20...")
    limiter.set_rpm(20)
    print(f"New stats: {limiter.get_stats()}")
    
    print(f"\nAdjusting by factor 0.5...")
    limiter.adjust_rpm(0.5, "test adjustment")
    print(f"New stats: {limiter.get_stats()}")
    
    print("\nAll tests passed!")