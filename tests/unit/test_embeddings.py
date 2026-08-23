"""嵌入分批单测:mock urlopen,验证 DashScope 请求不超过单次 20 条上限。

回归:删除文档/重建索引时会一次传几百个 chunk,不分批会撞 DashScope
的 400 InvalidParameter(batch size > 20)。FakeEmbeddings 抓不到这个,
必须显式 mock 网络层验证请求数。
"""

import json

from backend.services.embeddings import DashScopeEmbedding


class _FakeResponse:
    def __init__(self, payload: dict):
        self._bytes = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return self._bytes


def _embed_payload(offset, inputs):
    """构造 DashScope 响应:向量首元素 = 全局索引(offset + 批内序号),可跨批区分顺序。"""
    return {
        "data": [
            {"embedding": [float(offset + i), 0.0, 0.0]}
            for i, _ in enumerate(inputs)
        ]
    }


def test_embed_documents_batches_at_20(monkeypatch):
    """45 条文本 → 按 20+20+5 分 3 次请求,结果按原顺序拼接。"""
    texts = [f"文本{i}" for i in range(45)]
    calls = []
    offset = 0

    class _FakeUrlopen:
        def __call__(self, req, timeout=60, context=None):
            nonlocal offset
            body = json.loads(req.data.decode("utf-8"))
            calls.append(body["input"])
            resp = _FakeResponse(_embed_payload(offset, body["input"]))
            offset += len(body["input"])
            return resp

    monkeypatch.setattr("urllib.request.urlopen", _FakeUrlopen())
    emb = DashScopeEmbedding(model="m", api_key="sk-x", base_url="http://x")

    vectors = emb.embed_documents(texts)

    # 请求分批:每批 ≤20,总请求数 3,输入顺序保持
    assert len(calls) == 3
    assert [len(c) for c in calls] == [20, 20, 5]
    assert calls[0] == texts[:20]
    assert calls[1] == texts[20:40]
    assert calls[2] == texts[40:]
    # 返回 45 个向量,顺序与输入一致(靠向量首元素 = 全局索引区分)
    assert len(vectors) == 45
    assert [v[0] for v in vectors] == [float(i) for i in range(45)]
