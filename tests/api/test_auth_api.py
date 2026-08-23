"""认证 API:注册 / 登录 / 当前用户 / 角色规则。"""

from fastapi.testclient import TestClient

from backend.main import app


def test_register_first_user_is_admin():
    with TestClient(app) as c:
        r = c.post("/api/auth/register", json={"username": "admin", "password": "admin123"})
        assert r.status_code == 200
        data = r.json()
        assert data["user"]["role"] == "admin"
        assert data["token"]


def test_register_second_user_is_normal_user():
    with TestClient(app) as c:
        c.post("/api/auth/register", json={"username": "user1", "password": "aaaaaa"})
        r = c.post("/api/auth/register", json={"username": "user2", "password": "bbbbbb"})
        assert r.status_code == 200
        assert r.json()["user"]["role"] == "user"


def test_register_duplicate_returns_409():
    with TestClient(app) as c:
        c.post("/api/auth/register", json={"username": "dup", "password": "dupdup"})
        r = c.post("/api/auth/register", json={"username": "dup", "password": "xxxx11"})
        assert r.status_code == 409


def test_register_weak_input_rejected():
    with TestClient(app) as c:
        assert c.post("/api/auth/register", json={"username": "a", "password": "a1"}).status_code == 400
        assert c.post("/api/auth/register", json={"username": "x", "password": "123"}).status_code == 400


def test_login_ok_and_wrong_password():
    with TestClient(app) as c:
        c.post("/api/auth/register", json={"username": "login", "password": "secret1"})
        assert c.post("/api/auth/login", json={"username": "login", "password": "secret1"}).status_code == 200
        assert c.post("/api/auth/login", json={"username": "login", "password": "wrong!!"}).status_code == 401


def test_me_requires_token():
    with TestClient(app) as c:
        assert c.get("/api/auth/me").status_code == 401


def test_me_invalid_token_returns_401():
    with TestClient(app) as c:
        r = c.get("/api/auth/me", headers={"Authorization": "Bearer bad.token.here"})
        assert r.status_code == 401


def test_me_with_valid_token():
    with TestClient(app) as c:
        c.post("/api/auth/register", json={"username": "me", "password": "mememe"})
        token = c.post("/api/auth/login", json={"username": "me", "password": "mememe"}).json()["token"]
        r = c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["username"] == "me"


def test_non_admin_cannot_read_settings():
    """设置 API 仅管理员:普通用户 token 访问 → 403。"""
    from backend.services.rag_service import (
        get_manager as real_get_manager,
        get_service as real_get_service,
    )
    from tests.conftest import StubService

    app.dependency_overrides[real_get_manager] = lambda: object()
    app.dependency_overrides[real_get_service] = lambda: StubService()
    try:
        with TestClient(app) as c:
            # 每个测试是全新空库:先注册的成为 admin,第二个才是普通用户
            c.post("/api/auth/register", json={"username": "boss", "password": "boss12345"})
            c.post("/api/auth/register", json={"username": "nobody", "password": "no12345"})
            token = c.post("/api/auth/login", json={"username": "nobody", "password": "no12345"}).json()["token"]
            h = {"Authorization": f"Bearer {token}"}
            assert c.get("/api/settings", headers=h).status_code == 403
            assert c.post("/api/settings/reindex", headers=h).status_code == 403
    finally:
        app.dependency_overrides.clear()
