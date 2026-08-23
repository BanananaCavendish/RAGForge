"""IndexManager.reindex:切嵌入模型后全量重建 + 文本存储兜底。"""

import pytest
from langchain_core.embeddings.fake import FakeEmbeddings

from backend.core import config


def _write_doc(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_add_document_persists_chunk_texts(isolated_paths, fake_embeddings, tmp_path):
    """上传的文档原始文件会被删除,但 chunk 文本必须落盘(重建的底座)。"""
    from backend.services.index_manager import IndexManager

    manager = IndexManager()
    doc_id = manager.add_document(
        _write_doc(tmp_path, "a.md", "公司密码需要每 90 天更换一次。")
    )
    text_path = config.TEXT_DIR / f"{doc_id}.jsonl"
    assert text_path.exists()
    assert doc_id in manager.manifest


def test_reindex_rebuilds_with_new_embedding_dim(isolated_paths, tmp_path, monkeypatch):
    """切换嵌入模型(维度 16→32)后 reindex 能重建索引并可正常查询。"""
    from backend.services.index_manager import IndexManager

    emb16 = FakeEmbeddings(size=16)
    monkeypatch.setattr("backend.services.index_manager.get_embedding", lambda: emb16)
    manager = IndexManager()
    manager.add_document(_write_doc(tmp_path, "a.md", "差旅报销需要增值税发票与行程单。"))
    manager.add_document(_write_doc(tmp_path, "b.md", "境外出差住宿标准每晚 800 元。"))
    assert manager.vectorstore is not None

    # 设置页切换嵌入模型 → 换成 32 维
    emb32 = FakeEmbeddings(size=32)
    monkeypatch.setattr("backend.services.index_manager.get_embedding", lambda: emb32)
    done = manager.reindex()
    assert done == 2
    hits = manager.vectorstore.similarity_search("境外出差", k=1)
    assert len(hits) == 1


def test_reindex_falls_back_to_text_store(isolated_paths, tmp_path, monkeypatch):
    """FAISS 索引文件丢失/未加载时,reindex 从 data/texts/ 恢复文本再重建。"""
    from backend.services.index_manager import IndexManager

    emb = FakeEmbeddings(size=16)
    monkeypatch.setattr("backend.services.index_manager.get_embedding", lambda: emb)
    manager = IndexManager()
    manager.add_document(_write_doc(tmp_path, "a.md", "上班打卡最晚 8:45。"))

    # 模拟新进程:内存 all_docs 为空(FAISS 文件丢失),只剩 texts/ 文本存储
    fresh = IndexManager()
    fresh.all_docs = []
    fresh.vectorstore = None
    done = fresh.reindex()
    assert done == 1
    assert fresh.all_docs[0].page_content == "上班打卡最晚 8:45。"


def test_reindex_empty_raises(isolated_paths, fake_embeddings):
    from backend.services.index_manager import IndexManager

    with pytest.raises(RuntimeError):
        IndexManager().reindex()
