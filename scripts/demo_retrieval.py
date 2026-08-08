"""检索对比演示:对同一查询,展示三路结果,验证混合检索/重排的增益。

  vector         纯向量检索
  hybrid         向量 + BM25(RRF 融合)
  hybrid+rerank  混合召回后 cross-encoder 精排

用法:python scripts/demo_retrieval.py [--query "自定义问题"]
"""

import sys
from pathlib import Path

# Windows 控制台默认 GBK,打印 emoji/生僻字会崩;统一重配置为 UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# 让脚本无论从哪个目录运行都能 import backend
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse

from backend.core import config
from backend.services.retrieval import (
    build_hybrid_retriever,
    build_reranked_retriever,
    build_vector_retriever,
)


def show(label: str, docs: list) -> None:
    print(f"\n── {label} ──")
    for i, d in enumerate(docs, 1):
        src = d.metadata.get("source", "?")
        by = d.metadata.get("retrieved_by")
        by_str = f"  [命中路径: {'+'.join(by)}]" if by else ""
        print(f"  {i}. [{src}]{by_str}")
        print(f"     {d.page_content[:70].replace(chr(10), ' ')}...")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="报销要准备什么材料?")
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args()

    # 检索演示不需要 DeepSeek key(克隆即跑)
    from backend.services.index_manager import IndexManager

    manager = IndexManager()
    k = args.k

    print(f"查询: {args.query}\n")
    show("① 纯向量检索", build_vector_retriever(manager, k=k).invoke(args.query))
    show("② 混合检索 (向量+BM25, RRF)", build_hybrid_retriever(manager, k=k).invoke(args.query))
    show("③ 混合检索 + 重排", build_reranked_retriever(manager, top_k=k).invoke(args.query))


if __name__ == "__main__":
    main()
