"""真实环境端到端冒烟:注册→登录→会话→问答→上传→任务进度→流式。

只依赖 stdlib(urllib),用 venv python 跑:
    .venv/Scripts/python.exe scripts/smoke_test.py [base_url]

默认打到 http://127.0.0.1:8001。每个步骤失败会打印原因但不中断,
最后汇总 PASS/FAIL,便于一眼看出哪一环断。
"""

import json
import sys
import time
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8001"
USERNAME = "smoke_%s" % time.strftime("%m%d%H%M")

results = []


def step(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("  PASS  " if ok else "  FAIL  ") + name + (f"  [{detail}]" if detail else ""))


def req(method, path, body=None, token=None, files=None, timeout=120):
    headers = {}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if files:
        boundary = "smoke" + str(int(time.time() * 1000))
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        parts = []
        for name, (fname, content, ctype) in files.items():
            parts.append(
                (
                    f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; "
                    f"filename=\"{fname}\"\r\nContent-Type: {ctype}\r\n\r\n{content}\r\n"
                ).encode("utf-8")
            )
        parts.append(f"--{boundary}--\r\n".encode("utf-8"))
        data = b"".join(parts)
    elif body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    r = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def wait_task(token, task_id, max_waits=120):
    for _ in range(max_waits):
        code, body = req("GET", "/api/documents/tasks", token=token)
        tasks = json.loads(body).get("tasks", [])
        t = next((t for t in tasks if t["id"] == task_id), None)
        if t and t["status"] in ("done", "failed"):
            return t
        time.sleep(0.5)
    return {"status": "timeout"}


def main():
    print(f"\n=== 冒烟测试 @ {BASE} (用户 {USERNAME}) ===\n")

    # 1. 注册(可能已存在 → 直接登录)
    code, body = req("POST", "/api/auth/register", {"username": USERNAME, "password": "smoke12345"})
    if code == 200:
        step("注册新用户", True)
    else:
        step("注册新用户", code in (409, 400), f"HTTP {code}")

    # 2. 登录
    code, body = req("POST", "/api/auth/login", {"username": USERNAME, "password": "smoke12345"})
    if code != 200:
        step("登录", False, f"HTTP {code}: {body[:120]}")
        _report()
        return
    token = json.loads(body)["token"]
    role = json.loads(body)["user"]["role"]
    step("登录", True, f"role={role}")

    # 3. 当前用户
    code, body = req("GET", "/api/auth/me", token=token)
    step("GET /auth/me", code == 200 and json.loads(body)["username"] == USERNAME)

    # 4. 未带 token 被拒(鉴权生效)
    code, _ = req("GET", "/api/auth/me")
    step("无 token 访问被拒(401)", code == 401, f"HTTP {code}")

    # 5. 创建会话
    code, body = req("POST", "/api/sessions", token=token)
    step("创建会话", code == 200)
    if code != 200:
        _report()
        return
    sid = json.loads(body)["id"]

    # 6. 非流式问答(真实 DeepSeek,可能较慢或未配 key)
    code, body = req("POST", "/api/chat", {"question": "这家公司的团建政策是什么?", "session_id": sid}, token=token, timeout=120)
    if code == 200:
        ans = json.loads(body)["answer"]
        step("非流式问答", bool(ans.strip()), ans[:40])
    else:
        step("非流式问答", False, f"HTTP {code}: {body[:120]}")

    # 7. 消息持久化
    code, body = req("GET", f"/api/sessions/{sid}/messages", token=token)
    roles = [m["role"] for m in json.loads(body)["messages"]]
    step("消息落库(user+assistant)", roles == ["user", "assistant"], str(roles))

    # 8. 上传文档(异步摄取)
    code, body = req(
        "POST", "/api/documents", token=token,
        files={"file": ("smoke_policy.md", "# 冒烟测试政策\n本政策仅用于冒烟验证,公司每周五下午 4 点团建。\n", "text/markdown")},
    )
    if code == 202:
        task_id = json.loads(body)["task_id"]
        t = wait_task(token, task_id)
        step("上传→异步摄取完成", t["status"] == "done", t.get("status", "") + (" " + t.get("error", "") if t.get("error") else ""))
    else:
        step("上传→异步摄取", False, f"HTTP {code}: {body[:120]}")

    # 9. 文档列表能看到刚上传的
    code, body = req("GET", "/api/documents", token=token)
    docs = json.loads(body)["documents"]
    mine = [d for d in docs if d["filename"] == "smoke_policy.md"]
    step("文档列表包含刚上传的", len(mine) == 1 and mine[0]["owner"] == USERNAME,
         f"共{len(docs)}份,owner={mine[0]['owner'] if mine else '?'}")

    # 10. 流式问答(SSE)
    code, body = req("POST", "/api/chat/stream", {"question": "公司团建每年几次?", "session_id": sid}, token=token, timeout=120)
    if code == 200:
        events = [ln for ln in body.splitlines() if ln.startswith("data: ")]
        kinds = set()
        for ln in events:
            try:
                kinds.add(json.loads(ln[6:]).get("type"))
            except Exception:
                pass
        step("流式问答 SSE", "token" in kinds and "done" in kinds and events[-1].endswith("[DONE]"),
             f"事件类型={sorted(k for k in kinds if k)}")
    else:
        step("流式问答 SSE", False, f"HTTP {code}: {body[:120]}")

    _report()


def _report():
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n=== 结果:{passed}/{len(results)} 通过 ===")
    print("\n(说明)问答若为 HTTP 5xx,请检查 .env 里 DeepSeek key 是否有效;\n"
          "上传/鉴权/会话/持久化不依赖外部 API,失败即真实 bug。")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
