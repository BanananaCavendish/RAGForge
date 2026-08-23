"""IndexManager 单测:内容寻址幂等、增删一致、删空状态、持久化往返。

依赖 conftest 的 isolated_paths + fake_embeddings(零网络)。
"""

from pathlib import Path


def _write_md(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_add_document_is_idempotent(manager, tmp_path):
    """同一内容重复导入:doc_id 相同,manifest 只留一份,chunk 数不翻倍。"""
    f = _write_md(tmp_path, "doc.md", "晨光科技员工手册第一章,工作时间为上午九点。")
    first = manager.add_document(f)
    second = manager.add_document(f)

    assert first == second
    assert len(manager.manifest) == 1
    assert manager.list_documents()[0]["doc_id"] == first


def test_add_document_tracks_metadata(manager, tmp_path):
    f = _write_md(tmp_path, "policy.md", "密码口令不少于十二位,包含大小写字母数字特殊字符。")
    doc_id = manager.add_document(f, source_name="原始名字.md")

    info = manager.get_document(doc_id)
    assert info["filename"] == "原始名字.md"  # source_name 覆盖展示名
    assert info["fmt"] == "md"
    assert info["num_chunks"] >= 1

    # chunk 元数据里的 source 也用 source_name
    chunk = next(
        d for d in manager.all_docs if d.metadata["doc_id"] == doc_id
    )
    assert chunk.metadata["source"] == "原始名字.md"


def test_delete_document_removes_everything(manager, tmp_path):
    f1 = _write_md(tmp_path, "a.md", "员工手册:年休假满五年十二天。")
    f2 = _write_md(tmp_path, "b.md", "差旅报销:住宿一线城市每晚五百元。")
    id1 = manager.add_document(f1)
    manager.add_document(f2)

    assert manager.delete_document(id1) is True
    assert id1 not in manager.manifest
    assert not any(d.metadata["doc_id"] == id1 for d in manager.all_docs)
    # 剩下一份文档,索引仍可用
    assert len(manager.list_documents()) == 1


def test_delete_nonexistent_returns_false(manager):
    assert manager.delete_document("不存在") is False


def test_delete_last_document_cleans_faiss_dir(manager, tmp_path):
    """删空后 vectorstore 置 None 且 FAISS 目录被清理,重启不会加载过期索引。"""
    f = _write_md(tmp_path, "only.md", "唯一文档内容。")
    manager.add_document(f)
    assert manager.faiss_path.exists()

    manager.delete_document(manager.list_documents()[0]["doc_id"])

    assert manager.vectorstore is None
    assert manager.bm25 is None
    assert not manager.faiss_path.exists()


def test_manifest_round_trip(manager, tmp_path):
    """重新构造 IndexManager:从 manifest + FAISS 文件恢复全量 chunk。"""
    f = _write_md(tmp_path, "doc.md", "云文档支持导出为 PDF、Word 与 Markdown。")
    manager.add_document(f)
    chunk_count = len(manager.all_docs)

    # 重新构造(依赖 fake_embeddings 确定性,FAISS 可加载)
    from backend.services.index_manager import IndexManager

    reloaded = IndexManager()
    assert len(reloaded.all_docs) == chunk_count
    assert reloaded.list_documents()[0]["filename"] == "doc.md"
