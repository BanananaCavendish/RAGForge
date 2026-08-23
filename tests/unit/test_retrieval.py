"""检索层单测:RRF 融合、双路召回、空库守卫(bug#1 回归)。"""

from langchain_core.documents import Document

from backend.services.retrieval import (
    HybridRetriever,
    _EmptyRetriever,
    build_vector_retriever,
)


def _doc(doc_id: str, idx: int, content: str) -> Document:
    return Document(
        page_content=content,
        metadata={"doc_id": doc_id, "chunk_index": idx},
    )


def _empty_hybrid(k: int = 5) -> HybridRetriever:
    return HybridRetriever(vectorstore=None, bm25=None, corpus=[], k=k)


# ─── RRF 融合 ────────────────────────────────────────────────────


def test_rrf_fuse_merges_ranked_lists():
    """两路排名在名次上取倒数融合:同一文档在两路都出现则分数叠加。"""
    retriever = _empty_hybrid()
    a = _doc("d1", 0, "A")
    b = _doc("d2", 0, "B")
    c = _doc("d3", 0, "C")
    d = _doc("d4", 0, "D")

    fused = retriever._rrf_fuse(
        [[a, b, c], [c, a, d]], sources=("vector", "bm25")
    )

    # A: 1/61 + 1/62; C: 1/63 + 1/61 → A 应排 C 前,再是 B、D
    assert [f.metadata["doc_id"] for f in fused] == ["d1", "d3", "d2", "d4"]
    # 双路命中的文档 retrieved_by 应合并去重
    assert fused[0].metadata["retrieved_by"] == ["vector", "bm25"]
    # 分数 = 1/(60+rank+1) 求和,round 到 4 位
    assert fused[0].metadata["rrf_score"] == round(1 / 61 + 1 / 62, 4)


def test_rrf_fuse_dedupes_same_chunk_from_two_sources():
    """同一 (doc_id, chunk_index) 从两路都召回时只保留一条。"""
    retriever = _empty_hybrid()
    x = _doc("d1", 3, "X")
    fused = retriever._rrf_fuse([[x], [x]], sources=("vector", "bm25"))
    assert len(fused) == 1
    assert fused[0].metadata["doc_id"] == "d1"


def test_rrf_fuse_respects_top_n():
    retriever = _empty_hybrid()
    docs = [_doc(f"d{i}", 0, str(i)) for i in range(1, 6)]
    fused = retriever._rrf_fuse([docs], sources=("vector",), top_n=2)
    assert len(fused) == 2


# ─── 空知识库守卫(bug#1 回归) ──────────────────────────────────


def test_hybrid_retriever_empty_kb_returns_empty():
    """vectorstore 为 None 时 invoke 应返回空列表,而不是 AttributeError。"""
    retriever = _empty_hybrid()
    assert retriever.invoke("任意查询") == []


def test_build_vector_retriever_empty_kb_returns_empty_retriever():
    """空库下 build_vector_retriever 返回空检索器,不抛异常。"""

    class _FakeManager:
        vectorstore = None

    retriever = build_vector_retriever(_FakeManager())
    assert isinstance(retriever, _EmptyRetriever)
    assert retriever.invoke("任意查询") == []
