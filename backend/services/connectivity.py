"""连通性自检:设置页「测试连接」按钮的后端。

给客户用的配置面板,必须能在保存前验证 key / endpoint / model 是否真的可用,
而不是保存后才发现配错。每个测试都发一个最小真实请求:

  - LLM:      一次 chat 补全(max_tokens=1,几乎不花钱)
  - 嵌入:     编码一条短文本,顺带返回向量维度(帮助用户理解「维度变了要重建索引」)
  - 重排:     一个 mini 重排请求

失败返回 {ok: False, message: 可读错误};成功 {ok: True, message: 佐证信息}。
"""

import json
import ssl
import urllib.error
import urllib.request

_CTX = ssl.create_default_context()
_TIMEOUT = 30


def _post(url: str, body: dict, api_key: str) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT, context=_CTX) as r:
        return json.loads(r.read().decode("utf-8"))


def test_llm(base_url: str, api_key: str, model: str) -> dict:
    if not api_key:
        return {"ok": False, "message": "未配置 API Key"}
    url = f"{base_url.rstrip('/')}/chat/completions"
    try:
        data = _post(
            url,
            {"model": model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1},
            api_key,
        )
        usage = data.get("usage", {})
        return {"ok": True, "message": f"连通,模型 {model} 可用"}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        return {"ok": False, "message": f"HTTP {e.code}: {body}"}
    except Exception as e:  # noqa: BLE001 —— 网络/超时等
        return {"ok": False, "message": str(e)}


def test_embedding(base_url: str, api_key: str, model: str) -> dict:
    if not api_key:
        return {"ok": False, "message": "未配置 API Key"}
    url = f"{base_url.rstrip('/')}/embeddings"
    try:
        data = _post(url, {"model": model, "input": "测试连通性"}, api_key)
        dim = len(data["data"][0]["embedding"])
        return {"ok": True, "message": f"连通,模型 {model} 向量维度 {dim}"}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        return {"ok": False, "message": f"HTTP {e.code}: {body}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": str(e)}


def test_rerank(endpoint: str, api_key: str, model: str) -> dict:
    if not api_key:
        return {"ok": False, "message": "未配置 API Key"}
    try:
        data = _post(
            endpoint,
            {
                "model": model,
                "input": {"query": "测试", "documents": ["这是一条测试文本", "这是另一条"]},
                "parameters": {"top_n": 2, "return_documents": False},
            },
            api_key,
        )
        n = len(data.get("output", {}).get("results", []))
        return {"ok": True, "message": f"连通,模型 {model} 返回 {n} 个结果"}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        return {"ok": False, "message": f"HTTP {e.code}: {body}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": str(e)}
