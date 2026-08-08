"""命令行多轮对话 demo:验证 记忆 / 查询改写 / 引用 一条链路。

连问两轮,观察:
  - 第二轮「那额度上限呢?」如何被改写为带上下文的查询
  - 回答中的 [1][2] 引用标注与来源面板

用法:python scripts/demo_chat.py
"""

import sys
from pathlib import Path

# Windows 控制台默认 GBK:stdout 打印 emoji/生僻字会崩,stdin 读 UTF-8 管道会乱码;
# 统一把输入输出都重配置为 UTF-8(用管道喂中文问题也必须设 stdin)。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")

# 让脚本无论从哪个目录运行都能 import backend
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core import config
from backend.services.rag_service import get_service


def main() -> None:
    config.validate_config()
    service = get_service()
    session_id = "cli-demo"

    print("企业知识助手(命令行 demo,输入 q 退出)\n")
    while True:
        q = input("你: ").strip()
        if q.lower() in ("q", "quit", "exit"):
            break
        result = service.answer(session_id, q)
        print(f"\n🤖 {result['answer']}\n")
        for s in result["sources"]:
            print(
                f"    · 来源: {s['source']} 片段{s['chunk_index']}"
                f"  ({'+'.join(s['retrieved_by'] or [])})"
            )
        print()


if __name__ == "__main__":
    main()
