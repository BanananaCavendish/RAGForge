"""SSE 流式聊天:事件格式 / 结束标志 / 引用来源。"""


def test_chat_stream_sse_format(client):
    sid = client.post("/api/sessions").json()["id"]
    with client.stream(
        "POST", "/api/chat/stream", json={"question": "你好", "session_id": sid}
    ) as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("content-type", "")
        body = "".join(r.iter_text())

    lines = [ln for ln in body.splitlines() if ln.startswith("data: ")]
    assert lines  # 至少一条 SSE 事件
    assert any('"type": "token"' in ln for ln in lines)
    assert any('"type": "done"' in ln for ln in lines)
    assert any('"answer": "测试回答[1]"' in ln for ln in lines)
    assert '"source": "test.md"' in body
    assert body.rstrip().endswith("data: [DONE]")


def test_chat_stream_persists_messages(client):
    """流式回答同样落库:刷新后可读回同一段历史。"""
    sid = client.post("/api/sessions").json()["id"]
    with client.stream(
        "POST", "/api/chat/stream", json={"question": "流式问题", "session_id": sid}
    ):
        pass
    msgs = client.get(f"/api/sessions/{sid}/messages").json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["content"] == "测试回答[1]"
