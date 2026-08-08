"""全量建库(幂等):把 data/corpus/ 下所有文档导入 Chroma + BM25。

已导入过的文件(内容哈希一致)会被跳过,可重复执行。

用法:python scripts/build_index.py
输出:ingested 文档 / chunk 统计 + 一条调试查询验证召回。
"""

import os
import sys
from pathlib import Path

# Windows OpenMP DLL 冲突修复(必须在 import torch 前)
if os.name == "nt":
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

# Windows 控制台默认 GBK,打印 emoji/生僻字会崩;统一重配置为 UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# 让脚本无论从哪个目录运行都能 import backend
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import logging

logging.basicConfig(level=logging.INFO, format="%(message)s")

from backend.core import config
from backend.services.index_manager import IndexManager
from backend.services.retrieval import HybridRetriever

# 调试查询:验证「精确词检索」能否命中报销制度文档
DEBUG_QUERIES = [
    "差旅报销需要准备哪些材料?",
    "密码口令有什么要求?",
]


def main() -> None:
    # 建索引只需要本地 embedding 模型,不需要 DeepSeek key(克隆即跑)
    manager = IndexManager()

    files = sorted(config.CORPUS_DIR.glob("*"))
    if not files:
        print(f"❌ 没有语料,请先运行: python scripts/generate_corpus.py ({config.CORPUS_DIR})")
        return

    for f in files:
        manager.add_document(f)

    print(f"\n📚 索引统计: {len(manager.list_documents())} 个文档 / {len(manager.all_docs)} 个 chunk")
    print("   注册表:", config.MANIFEST_PATH)

    # 调试查询:用混合检索看每条的命中来源
    retriever = HybridRetriever(
        vectorstore=manager.vectorstore,
        bm25=manager.bm25,
        corpus=manager.all_docs,
        k=5,
    )
    print("\n🧪 调试查询:")
    for q in DEBUG_QUERIES:
        docs = retriever.invoke(q)
        sources = [d.metadata.get("source", "?") for d in docs]
        print(f"   「{q}」→ {sources}")


if __name__ == "__main__":
    main()
