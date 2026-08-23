"""设置 API:GET 掩码回显 / PUT 保存 / 重建索引 / 连接测试 / 一致性守卫。"""

import time

from backend.core import config


def test_get_settings_masks_keys(client, fake_env):
    res = client.get("/api/settings")
    assert res.status_code == 200
    data = res.json()
    assert data["llm"]["api_key"].endswith("****7890")
    assert "1234567890" not in data["llm"]["api_key"]  # 完整 key 绝不出现在响应
    assert data["embedding"]["has_key"] is True
    assert data["rerank"]["enabled"] is True
    assert data["options"]["llm_providers"]
    assert data["needs_reindex"] is False


def test_put_settings_partial_and_persisted(client, fake_env):
    res = client.put(
        "/api/settings", json={"embedding": {"model": "text-embedding-v3"}}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["embedding"]["model"] == "text-embedding-v3"
    assert data["llm"]["model"] == "deepseek-chat"  # 未提交字段不动

    # 已持久化到磁盘(重新加载后仍生效)
    from backend.core import settings as core_settings

    core_settings.reload_settings()
    assert core_settings.load_settings().embedding.model == "text-embedding-v3"


def test_put_clears_api_key(client, fake_env):
    res = client.put("/api/settings", json={"embedding": {"api_key": ""}})
    assert res.status_code == 200
    assert res.json()["embedding"]["has_key"] is False


def test_put_rejects_invalid_provider(client, fake_env):
    res = client.put("/api/settings", json={"embedding": {"provider": "nonsense"}})
    assert res.status_code == 400


def test_test_connection_routes_to_each_service(client, fake_env, monkeypatch):
    from backend.services import connectivity

    monkeypatch.setattr(
        connectivity, "test_llm", lambda *a, **k: {"ok": True, "message": "OK"}
    )
    monkeypatch.setattr(
        connectivity, "test_embedding", lambda *a, **k: {"ok": True, "message": "OK"}
    )
    monkeypatch.setattr(
        connectivity, "test_rerank", lambda *a, **k: {"ok": True, "message": "OK"}
    )
    res = client.post("/api/settings/test", json={})
    assert res.status_code == 200
    data = res.json()
    assert data["llm"]["ok"] is True
    assert data["embedding"]["ok"] is True
    assert data["rerank"]["ok"] is True


def test_test_connection_skips_disabled_rerank(client, fake_env, monkeypatch):
    from backend.core import settings as core_settings
    from backend.services import connectivity

    core_settings.update_settings({"rerank": {"enabled": False}})
    monkeypatch.setattr(
        connectivity, "test_llm", lambda *a, **k: {"ok": True, "message": "OK"}
    )
    monkeypatch.setattr(
        connectivity, "test_embedding", lambda *a, **k: {"ok": True, "message": "OK"}
    )
    res = client.post("/api/settings/test", json={})
    data = res.json()
    assert data["rerank"]["ok"] is None  # 未启用 → 跳过


def test_chat_blocked_until_reindex(client, fake_env):
    """嵌入模型变更且未重建 → 提问返回 409 + 明确指引,而不是 500 崩溃。"""
    config.MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.MANIFEST_PATH.write_text("{}", encoding="utf-8")
    from backend.core import settings as core_settings

    core_settings.update_settings({"embedding": {"model": "text-embedding-v3"}})
    res = client.post("/api/chat", json={"question": "出差报销材料", "session_id": "s"})
    assert res.status_code == 409
    assert "重建索引" in res.json()["detail"]


def test_reindex_endpoint_rebuilds_and_clears_flag(
    isolated_paths, tmp_path, monkeypatch, test_user
):
    """POST /reindex → 后台线程重建 → 轮询 GET 直到完成 → 标志清除。"""
    from fastapi.testclient import TestClient
    from langchain_core.embeddings.fake import FakeEmbeddings

    from backend.api.deps import get_admin_user, get_current_user
    from backend.core import settings as core_settings
    from backend.main import app
    from backend.services.index_manager import IndexManager
    from backend.services.rag_service import (
        get_manager as real_get_manager,
        get_service as real_get_service,
    )

    emb = FakeEmbeddings(size=16)
    monkeypatch.setattr("backend.services.index_manager.get_embedding", lambda: emb)
    manager = IndexManager()
    p = tmp_path / "a.md"
    p.write_text("公司密码每 90 天更换一次。", encoding="utf-8")
    manager.add_document(p)

    # 切嵌入模型 → 需要重建
    core_settings.update_settings({"embedding": {"model": "text-embedding-v3"}})

    app.dependency_overrides[real_get_manager] = lambda: manager
    app.dependency_overrides[real_get_service] = lambda: object()
    # 设置路由已接入管理员鉴权 → 测试里直接放行
    app.dependency_overrides[get_current_user] = lambda: test_user
    app.dependency_overrides[get_admin_user] = lambda: test_user
    try:
        with TestClient(app) as c:
            assert c.get("/api/settings").json()["needs_reindex"] is True
            res = c.post("/api/settings/reindex")
            assert res.status_code == 200
            assert res.json()["started"] is True

            for _ in range(100):
                s = c.get("/api/settings").json()
                if not s["rebuilding"]:
                    break
                time.sleep(0.05)
            assert s["rebuilding"] is False
            assert s["last_rebuild_error"] == ""
            assert s["needs_reindex"] is False
    finally:
        app.dependency_overrides.clear()
