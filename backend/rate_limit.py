import os
import time
import asyncio
from collections import defaultdict, deque

from fastapi import HTTPException, status


class SlidingWindowLimiter:
    """单进程内存滑动窗口限流，够用且无外部依赖。"""

    def __init__(self, limit: int, window_seconds: int = 60):
        self.limit = max(1, limit)
        self.window = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(self, key: str) -> None:
        now = time.monotonic()
        async with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                retry_after = max(1, int(self.window - (now - hits[0])))
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"请求过于频繁，请 {retry_after} 秒后再试",
                    headers={"Retry-After": str(retry_after)},
                )
            hits.append(now)

    def reset(self) -> None:
        self._hits.clear()


chat_limiter = SlidingWindowLimiter(int(os.getenv("CHAT_RATE_LIMIT", "20")), 60)
auth_limiter = SlidingWindowLimiter(int(os.getenv("AUTH_RATE_LIMIT", "10")), 60)
