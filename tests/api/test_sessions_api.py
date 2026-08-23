"""会话 API:创建 / 列表 / 消息 / 删除 + 用户间隔离。"""

from fastapi.testclient import TestClient

from backend.main import app
from tests.conftest import StubService


def _register(c, username, password):
    c.post("/api/auth/register", json={"username": username, "password": password})
    token = c.post("/api/auth/login", json={"username": username, "password": password}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_session_crud():
    with TestClient(app) as c:
        h = _register(c, "alice", "alice123")
        r = c.post("/api/sessions", headers=h)
        assert r.status_code == 200
        sid = r.json()["id"]
        assert r.json()["title"] == "新会话"

        assert c.get("/api/sessions", headers=h).json()[0]["id"] == sid
        assert c.get(f"/api/sessions/{sid}/messages", headers=h).json()["messages"] == []
        assert c.delete(f"/api/sessions/{sid}", headers=h).json()["deleted"] is True
        assert c.get("/api/sessions", headers=h).json() == []


def test_session_messages_persist_after_chat():
    from backend.services.rag_service import get_service as real_get_service

    app.dependency_overrides[real_get_service] = lambda: StubService()
    try:
        with TestClient(app) as c:
            h = _register(c, "bob", "bob12345")
            sid = c.post("/api/sessions", headers=h).json()["id"]
            c.post("/api/chat", headers=h, json={"question": "你好", "session_id": sid})
            msgs = c.get(f"/api/sessions/{sid}/messages", headers=h).json()["messages"]
            assert [m["role"] for m in msgs] == ["user", "assistant"]
            assert msgs[0]["content"] == "你好"
            assert msgs[1]["content"] == "测试回答[1]"
    finally:
        app.dependency_overrides.clear()


def test_session_isolation_between_users():
    with TestClient(app) as c:
        ha = _register(c, "u_a", "user_aaa")
        hb = _register(c, "u_b", "user_bbb")
        sid_a = c.post("/api/sessions", headers=ha).json()["id"]
        # B 看不到 A 的会话,也读不到 / 删不掉 A 的消息
        assert c.get("/api/sessions", headers=hb).json() == []
        assert c.get(f"/api/sessions/{sid_a}/messages", headers=hb).status_code == 404
        assert c.delete(f"/api/sessions/{sid_a}", headers=hb).status_code == 404


def test_session_requires_auth():
    with TestClient(app) as c:
        assert c.get("/api/sessions").status_code == 401
        assert c.post("/api/sessions").status_code == 401
