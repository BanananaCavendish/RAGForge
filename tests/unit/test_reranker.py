"""重排单测:API 请求构造、响应解析、降级逻辑。全部 mock urlopen,零外网。"""

import json

import pytest
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from backend.core import config
from backend.services.reranker import DashScopeReranker, get_reranker
from backend.services.retrieval import RerankRetriever


# ─── 辅助:假的 urlopen 响应 ────────────────────────────────────────


class _FakeResponse:
    def __init__(self, payload: dict):
        self._bytes = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return self._bytes


def _install_urlopen(monkeypatch, payload: dict):
    """把 urllib.request.urlopen 换成返回固定响应的假实现,并记录请求体。"""
    captured = {}

    class _FakeUrlopen:
        def __call__(self, req, timeout=60, context=None):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            captured["headers"] = dict(req.headers)
            return _FakeResponse(payload)

    monkeypatch.setattr("urllib.request.urlopen", _FakeUrlopen())
    return captured


# ─── DashScopeReranker.rank ───────────────────────────────────────


def test_rank_sends_correct_request(monkeypatch):
    """请求体应包含 model / input 结构 / 一次批量传全部候选。"""
    captured = _install_urlopen(
        monkeypatch,
        {"output": {"results": [{"index": 0, "relevance_score": 0.9}]}},
    )
    reranker = DashScopeReranker(model="gte-rerank-v2", api_key="sk-x", endpoint="http://x")

    reranker.rank("请假几天算事假", ["文档A", "文档B"])

    body = captured["body"]
    assert body["model"] == "gte-rerank-v2"
    assert body["input"]["query"] == "请假几天算事假"
    assert body["input"]["documents"] == ["文档A", "文档B"]
    # top_n 传全部候选,批量打一次分
    assert body["parameters"]["top_n"] == 2
    assert body["parameters"]["return_documents"] is False
    assert captured["headers"]["Authorization"] == "Bearer sk-x"


def test_rank_maps_scores_back_to_input_order(monkeypatch):
    """结果按相关度降序返回,须按 index 字段还原到输入顺序;缺失项补 0.0。"""
    _install_urlopen(
        monkeypatch,
        {
            "output": {
                "results": [
                    {"index": 1, "relevance_score": 0.95},
                    {"index": 0, "relevance_score": 0.40},
                ]
            }
        },
    )
    reranker = DashScopeReranker(model="m", api_key="sk-x", endpoint="http://x")

    scores = reranker.rank("q", ["a", "b", "c"])
    assert scores == [0.40, 0.95, 0.0]


def test_rank_empty_documents_returns_empty(monkeypatch):
    _install_urlopen(monkeypatch, {"output": {"results": []}})
    reranker = DashScopeReranker(model="m", api_key="sk-x", endpoint="http://x")
    assert reranker.rank("q", []) == []


def test_rank_http_error_raises_runtime_error(monkeypatch):
    class _ErrorResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self) -> bytes:
            return b"invalid api key"

    class _FailUrlopen:
        def __call__(self, req, timeout=60, context=None):
            from urllib.error import HTTPError

            raise HTTPError(
                req.full_url, 401, "Unauthorized", {}, _ErrorResponse()
            )

    monkeypatch.setattr("urllib.request.urlopen", _FailUrlopen())
    reranker = DashScopeReranker(model="m", api_key="bad", endpoint="http://x")

    with pytest.raises(RuntimeError, match="HTTP 401"):
        reranker.rank("q", ["a"])


# ─── 工厂与缺 key 提示 ─────────────────────────────────────────────


def test_get_reranker_missing_api_key_raises_value_error(monkeypatch):
    """RERANK_PROVIDER=api 但没配 DASHSCOPE_API_KEY 时应给出清晰中文报错。"""
    from backend.services import reranker as reranker_mod

    monkeypatch.setattr(config, "RERANK_PROVIDER", "api")
    monkeypatch.setattr(config, "DASHSCOPE_API_KEY", "")
    monkeypatch.setattr(reranker_mod, "_reranker", None)
    monkeypatch.setattr(reranker_mod, "_dashscope_reranker_singleton", None)

    with pytest.raises(ValueError, match="DASHSCOPE_API_KEY"):
        get_reranker()


# ─── RerankRetriever:排序 + 优雅降级 ─────────────────────────────


class _FakeBase(BaseRetriever):
    """返回固定文档序列的假 base retriever(RerankRetriever.base 要求 BaseRetriever)。"""

    docs: list

    def _get_relevant_documents(self, query: str) -> list[Document]:
        return list(self.docs)


class _FakeReranker:
    def __init__(self, scores=None, exc=None):
        self.scores = scores
        self.exc = exc
        self.calls = []

    def rank(self, query, documents):
        self.calls.append((query, documents))
        if self.exc is not None:
            raise self.exc
        return self.scores


def _docs():
    return [
        Document(page_content="A", metadata={"doc_id": "d1", "chunk_index": 0}),
        Document(page_content="B", metadata={"doc_id": "d2", "chunk_index": 0}),
        Document(page_content="C", metadata={"doc_id": "d3", "chunk_index": 0}),
    ]


def test_rerank_retriever_sorts_by_score(monkeypatch):
    """重排后按分数降序,并写 metadata['rerank_score']。"""
    fake = _FakeReranker(scores=[0.1, 0.9, 0.5])  # 与输入顺序对应
    monkeypatch.setattr(
        "backend.services.reranker.get_reranker", lambda: fake
    )

    retriever = RerankRetriever(base=_FakeBase(docs=_docs()), top_k=4)
    out = retriever.invoke("q")

    # 按分数降序:B(0.9) → C(0.5) → A(0.1)
    assert [d.page_content for d in out] == ["B", "C", "A"]
    assert out[0].metadata["rerank_score"] == 0.9
    assert out[1].metadata["rerank_score"] == 0.5


def test_rerank_retriever_respects_top_k(monkeypatch):
    fake = _FakeReranker(scores=[0.9, 0.1, 0.5])
    monkeypatch.setattr(
        "backend.services.reranker.get_reranker", lambda: fake
    )
    retriever = RerankRetriever(base=_FakeBase(docs=_docs()), top_k=2)
    out = retriever.invoke("q")
    assert [d.page_content for d in out] == ["A", "C"]


def test_rerank_retriever_degrades_on_api_error(monkeypatch):
    """重排 API 故障:warning + 按 base 原序返回,绝不拖垮对话。"""
    fake = _FakeReranker(exc=RuntimeError("DashScope 超时"))
    monkeypatch.setattr(
        "backend.services.reranker.get_reranker", lambda: fake
    )

    retriever = RerankRetriever(base=_FakeBase(docs=_docs()), top_k=4)
    out = retriever.invoke("q")

    assert [d.page_content for d in out] == ["A", "B", "C"]  # 原序
    assert all("rerank_score" not in d.metadata for d in out)
