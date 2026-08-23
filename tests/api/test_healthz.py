"""健康检查:GET /healthz 无需登录,返回索引与数据库状态。"""


def test_healthz_ok_without_auth():
    from fastapi.testclient import TestClient

    from backend.main import app

    with TestClient(app) as c:
        r = c.get("/healthz")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "index" in data and "docs" in data["index"]
    assert data["db"] == "ok"
