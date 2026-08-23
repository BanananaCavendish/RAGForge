"""文档 API 测试:上传(异步摄取)/ 删除 / 列表 / 预览 / 路径遍历(bug#2 回归)。

上传是异步的:POST 返回 202 + task_id,后台线程摄取;测试用 wait_ingest 轮询
任务列表等它 done,再断言文档已入库。
"""


def test_upload_document(client, wait_ingest):
    res = client.post(
        "/api/documents",
        files={"file": ("员工手册.md", "# 标题\n内容说明。", "text/markdown")},
    )
    assert res.status_code == 202
    assert res.json()["status"] == "pending"
    task = wait_ingest(client)
    assert task["status"] == "done"
    assert task["doc_id"]

    docs = client.get("/api/documents").json()["documents"]
    assert any(d["filename"] == "员工手册.md" and d["fmt"] == "md" for d in docs)


def test_upload_unsupported_suffix(client):
    res = client.post(
        "/api/documents",
        files={"file": ("evil.exe", b"MZ", "application/octet-stream")},
    )
    assert res.status_code == 400
    assert "不支持" in res.json()["detail"]


def test_upload_path_traversal_sanitized(client, isolated_paths, wait_ingest):
    """filename 带 `../../` 路径遍历:展示名被净化,临时文件被清理。"""
    res = client.post(
        "/api/documents",
        files={"file": ("../../evil.md", "# evil\n内容。", "text/markdown")},
    )
    assert res.status_code == 202
    wait_ingest(client)
    docs = client.get("/api/documents").json()["documents"]
    assert docs[0]["filename"] == "evil.md"  # 剥离开路径,不可能是 ../..
    assert ".." not in docs[0]["filename"]

    # 后台摄取线程在 finally 里清理了临时文件(uploads 目录为空)
    uploads = isolated_paths / "uploads"
    assert list(uploads.iterdir()) == []


def test_upload_windows_style_path_sanitized(client, wait_ingest):
    """兼容 Windows 盘符路径: `C:\\evil.md` 也被剥离。"""
    res = client.post(
        "/api/documents",
        files={"file": ("C:\\fake\\evil.md", "# evil\n内容。", "text/markdown")},
    )
    assert res.status_code == 202
    wait_ingest(client)
    docs = client.get("/api/documents").json()["documents"]
    assert docs[0]["filename"] == "evil.md"


def test_list_documents_empty(client):
    res = client.get("/api/documents")
    assert res.status_code == 200
    assert res.json() == {"documents": []}


def test_delete_nonexistent_returns_404(client):
    res = client.delete("/api/documents/不存在的id")
    assert res.status_code == 404


def test_delete_document(client, wait_ingest):
    up = client.post(
        "/api/documents",
        files={"file": ("a.md", "# A\n内容一。", "text/markdown")},
    )
    wait_ingest(client)
    docs = client.get("/api/documents").json()["documents"]
    doc_id = docs[0]["doc_id"]

    res = client.delete(f"/api/documents/{doc_id}")
    assert res.status_code == 200
    assert res.json()["deleted"] is True
    assert client.get("/api/documents").json()["documents"] == []


def test_preview_document(client, wait_ingest):
    res = client.post(
        "/api/documents",
        files={"file": ("preview.md", "# 标题\n第一段内容。\n第二段内容。", "text/markdown")},
    )
    wait_ingest(client)
    doc_id = client.get("/api/documents").json()["documents"][0]["doc_id"]

    p = client.get(f"/api/documents/{doc_id}/preview")
    assert p.status_code == 200
    data = p.json()
    assert data["filename"] == "preview.md"
    assert data["chunks"]  # 至少一个 chunk
    assert "第一段" in data["chunks"][0]["text"]


def test_preview_unknown_doc_404(client):
    assert client.get("/api/documents/不存在的id/preview").status_code == 404
