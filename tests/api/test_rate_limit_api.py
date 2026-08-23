"""限流:每用户每分钟聊天请求上限 → 429 + Retry-After。"""

import pytest
from fastapi import HTTPException


def test_fixed_window_limiter_blocks_over_limit():
    from backend.services.rate_limit import FixedWindowLimiter

    limiter = FixedWindowLimiter(2)
    limiter.check("key1")
    limiter.check("key1")
    with pytest.raises(HTTPException) as exc_info:
        limiter.check("key1")
    assert exc_info.value.status_code == 429
    assert "Retry-After" in exc_info.value.headers


def test_fixed_window_limiter_per_key():
    from backend.services.rate_limit import FixedWindowLimiter

    limiter = FixedWindowLimiter(1)
    limiter.check("user_a")
    limiter.check("user_b")  # 不同用户互不影响
    with pytest.raises(HTTPException):
        limiter.check("user_a")


def test_chat_returns_429_after_limit(client, monkeypatch):
    """API 级:把聊天限流改成 2 次/分钟,第 3 次提问被拒。"""
    from backend.api.routes import chat as chat_route
    from backend.services.rate_limit import FixedWindowLimiter

    monkeypatch.setattr(chat_route, "chat_limiter", FixedWindowLimiter(2))
    sid = client.post("/api/sessions").json()["id"]
    for _ in range(2):
        r = client.post("/api/chat", json={"question": "hi", "session_id": sid})
        assert r.status_code == 200
    r3 = client.post("/api/chat", json={"question": "hi", "session_id": sid})
    assert r3.status_code == 429
    assert "Retry-After" in r3.headers
