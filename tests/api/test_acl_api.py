"""文档 ACL:admin 全量 / 普通用户只见语料库+自己上传的 / 检索层权限过滤。

这些测试走真实 JWT 认证流程(注册→登录→带 Authorization 头),验证
多用户隔离不是纸面功能:普通用户既看不到、也删不掉管理员的私有文档。
"""

import time

from fastapi.testclient import TestClient

from backend.main import app
from tests.conftest import StubService


def _register(c, username, password):
    c.post("/api/auth/register", json={"username": username, "password": password})
    token = c.post("/api/auth/login", json={"username": username, "password": password}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _wait_done(c, headers):
    for _ in range(100):
        tasks = c.get("/api/documents/tasks", headers=headers).json()["tasks"]
        if tasks and all(t["status"] in ("done", "failed") for t in tasks):
            assert tasks[0]["status"] == "done", tasks[0].get("error")
            return tasks[0]
        time.sleep(0.05)
    raise AssertionError("摄取超时")


def _override(manager):
    from backend.services.rag_service import (
        get_manager as real_get_manager,
        get_service as real_get_service,
    )

    app.dependency_overrides[real_get_manager] = lambda: manager
    app.dependency_overrides[real_get_service] = lambda: StubService()


def test_user_cannot_see_or_operate_admin_private_doc(isolated_paths, manager):
    _override(manager)
    try:
        with TestClient(app) as c:
            ha = _register(c, "admin", "admin123")
            r = c.post(
                "/api/documents", headers=ha,
                files={"file": ("private.md", "# 机密\n内部预算 100 万。", "text/markdown")},
            )
            assert r.status_code == 202
            _wait_done(c, ha)
            priv_id = [
                d for d in c.get("/api/documents", headers=ha).json()["documents"]
                if d["filename"] == "private.md"
            ][0]["doc_id"]

            hb = _register(c, "bob", "bob12345")
            assert c.get("/api/documents", headers=hb).json()["documents"] == []
            assert c.get(f"/api/documents/{priv_id}/preview", headers=hb).status_code == 403
            assert c.delete(f"/api/documents/{priv_id}", headers=hb).status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_corpus_doc_visible_to_all(isolated_paths, manager, tmp_path):
    """CLI 建库的文档(uploaded_by NULL)在启动时同步为语料库文档 → 全员可见。"""
    p = tmp_path / "corpus.md"
    p.write_text("公司团建每年一次。", encoding="utf-8")
    manager.add_document(p)  # 无 DB 元数据 = 语料库文档

    _override(manager)
    try:
        with TestClient(app) as c:  # lifespan 触发 manifest → DB 同步
            hb = _register(c, "bob", "bob12345")
            docs = c.get("/api/documents", headers=hb).json()["documents"]
            assert len(docs) == 1
            assert docs[0]["filename"] == "corpus.md"
            assert docs[0]["owner"] is None
    finally:
        app.dependency_overrides.clear()


def test_rag_service_filters_docs_by_allowed(empty_service):
    """检索层权限过滤:allowed 之外的文档不进 sources(核心防线,单元级验证)。"""
    from langchain_core.documents import Document

    docs = [
        Document(page_content="a", metadata={"doc_id": "aaa"}),
        Document(page_content="b", metadata={"doc_id": "bbb"}),
    ]
    filtered = empty_service._filter_docs(docs, {"aaa"})
    assert [d.metadata["doc_id"] for d in filtered] == ["aaa"]
    assert empty_service._filter_docs(docs, None) == docs  # admin / CLI 不过滤
    assert empty_service._filter_docs(docs, set()) == []
