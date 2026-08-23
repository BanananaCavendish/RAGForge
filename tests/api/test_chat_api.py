"""聊天 API 测试:响应模型 + 会话归属 + 空库优雅降级(bug#1 回归)。

认证:client 夹具已覆盖 get_current_user(admin),这里聚焦路由逻辑。
"""

from fastapi.testclient import TestClient

from backend.main import app


def test_chat_returns_canned_answer(client):
    """Stub 服务:先建会话再提问,验证路由接线与响应 schema。"""
    sid = client.post("/api/sessions").json()["id"]
    res = client.post("/api/chat", json={"question": "你好", "session_id": sid})
    assert res.status_code == 200
    data = res.json()
    assert data["answer"] == "测试回答[1]"
    assert data["session_id"] == sid  # 归属校验通过 → 复用原会话
    src = data["sources"][0]
    assert src["source"] == "test.md"
    assert src["retrieved_by"] == ["vector", "bm25"]


def test_chat_auto_creates_session_when_absent(client):
    """未传 session_id → 服务端自动新建会话(响应里返回新 id)。"""
    res = client.post("/api/chat", json={"question": "你好"})
    assert res.status_code == 200
    assert res.json()["session_id"]


def test_chat_forbidden_for_foreign_session(client):
    """别人的会话 → 403,绝不写进别人的历史里。"""
    from backend.db import repositories

    other = repositories.create_user("other", "x", role="user")
    sid = repositories.create_session(other["id"])
    res = client.post("/api/chat", json={"question": "你好", "session_id": sid})
    assert res.status_code == 403


def test_chat_empty_kb_returns_graceful(manager, make_fake_llm, test_user):
    """空知识库:走真实 RAGService 链路,应返回「未检索到」而非 500。

    bug#1 回归:修复前 retrieval 在 vectorstore=None 时抛 AttributeError,
    被 chat.py 统一转成 500;修复后应优雅返回「未检索到」。
    """
    from backend.api.deps import get_current_user
    from backend.services.rag_service import (
        RAGService,
        get_service as real_get_service,
    )

    app.dependency_overrides[real_get_service] = lambda: RAGService(
        manager, llm=make_fake_llm(responses=[])
    )
    app.dependency_overrides[get_current_user] = lambda: test_user
    with TestClient(app) as c:
        res = c.post("/api/chat", json={"question": "报销需要什么?", "session_id": "e2e"})
    app.dependency_overrides.clear()

    assert res.status_code == 200
    assert "未检索到" in res.json()["answer"]
    assert res.json()["sources"] == []
