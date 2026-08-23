"""简易限流:固定窗口计数,每用户每分钟可提问 N 次。

设计取舍:
- 内存实现,单进程部署够用(本项目单 uvicorn worker 起)。
- 多 worker / 多实例部署时,把计数挪到 Redis(INCR + EXPIRE)即可,
  接口形状不变(check(key) 抛 429)。

为什么放「固定窗口」而不是令牌桶?
  够用且简单——聊天请求每个都花真金白银(LLM token),限流目的是
  防单个用户刷爆成本,不需要平滑流量。实现直观,面试讲得清。
"""

import threading
import time

from fastapi import HTTPException

from backend.core import config


class FixedWindowLimiter:
    def __init__(self, limit: int, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, list[float]] = {}  # key -> 窗口内时间戳
        self._lock = threading.Lock()

    def check(self, key: object) -> None:
        """窗口内超过上限则抛 429;否则记录本次请求并放行。"""
        now = time.time()
        with self._lock:
            hits = [t for t in self._hits.get(str(key), []) if now - t < self.window]
            if len(hits) >= self.limit:
                retry_after = max(1, int(self.window - (now - hits[0])) + 1)
                raise HTTPException(
                    status_code=429,
                    detail=f"请求过于频繁,请 {retry_after} 秒后再试",
                    headers={"Retry-After": str(retry_after)},
                )
            hits.append(now)
            self._hits[str(key)] = hits

    def reset(self) -> None:
        """清空计数(测试用 / 配置变更后)。"""
        with self._lock:
            self._hits.clear()


# 全局限流器:聊天接口(非流式 + 流式)共用,按用户 id 计数
chat_limiter = FixedWindowLimiter(config.CHAT_RATE_LIMIT_PER_MINUTE)
