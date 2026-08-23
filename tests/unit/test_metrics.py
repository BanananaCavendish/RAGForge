"""评估指标单测:recall@k / MRR / 文档级去重。"""

from langchain_core.documents import Document

from backend.evaluation.metrics import (
    RetrievalScores,
    dedupe_doc_ids,
    mrr,
    recall_at_k,
)


def test_recall_at_k():
    assert recall_at_k(["a", "b"], {"a"}, 1) == 1.0
    assert recall_at_k(["a", "b"], {"c"}, 3) == 0.0
    assert recall_at_k(["a", "b"], {"b", "c"}, 2) == 0.5
    assert recall_at_k(["a", "b"], set(), 1) == 1.0  # 空 golden 视为满分


def test_mrr():
    assert mrr(["a", "b", "c"], {"b"}) == 0.5
    assert mrr(["a", "b"], {"b", "c"}) == 0.5
    assert mrr(["a", "b"], {"z"}) == 0.0


def test_dedupe_doc_ids_preserves_rank_order():
    def d(doc_id):
        return Document(page_content="x", metadata={"doc_id": doc_id})

    assert dedupe_doc_ids([d("d1"), d("d1"), d("d2")]) == ["d1", "d2"]


def test_scores_accumulate_and_finalize():
    s = RetrievalScores()
    s.accumulate(["a", "b"], {"a"})  # recall@1=1, recall@3=1, mrr=1
    s.accumulate(["x", "y"], {"z"})  # 全 0
    res = s.finalize(2)
    assert res["recall@1"] == 0.5
    assert res["recall@3"] == 0.5
    assert res["recall@5"] == 0.5
    assert res["mrr"] == 0.5


def test_recall_at_1_is_strictest():
    """recall@1 只认「正确文档排首位」,比 recall@3 严格得多。"""
    s = RetrievalScores()
    s.accumulate(["a", "x", "y"], {"a"})  # 首位命中
    s.accumulate(["x", "a", "y"], {"a"})  # 第 2 位才命中
    res = s.finalize(2)
    assert res["recall@1"] == 0.5
    assert res["recall@3"] == 1.0
    assert res["mrr"] == 0.75


def test_scores_finalize_zero_returns_empty():
    assert RetrievalScores().finalize(0) == {}
