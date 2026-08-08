"""CLI 文档管理:增 / 删 / 替换 / 列出。验证「增量更新」不用全量重建。

用法:
  python scripts/manage_docs.py list
  python scripts/manage_docs.py add   <文件路径>
  python scripts/manage_docs.py rm    <doc_id>
  python scripts/manage_docs.py replace <doc_id> <文件路径>
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
from backend.services.index_manager import IndexManager


def main() -> None:
    parser = argparse.ArgumentParser(description="文档增量管理")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list")
    p_add = sub.add_parser("add")
    p_add.add_argument("path")
    p_rm = sub.add_parser("rm")
    p_rm.add_argument("doc_id")
    p_rep = sub.add_parser("replace")
    p_rep.add_argument("doc_id")
    p_rep.add_argument("path")

    args = parser.parse_args()
    manager = IndexManager()

    if args.cmd == "list":
        docs = manager.list_documents()
        if not docs:
            print("(空) 没有已入库文档")
        for d in docs:
            print(f"  {d['doc_id']}  {d['filename']}  {d['num_chunks']} chunks  {d['added_at']}")

    elif args.cmd == "add":
        path = Path(args.path)
        if not path.exists():
            print(f"❌ 文件不存在: {path}")
            sys.exit(1)
        doc_id = manager.add_document(path)
        print(f"✅ 已导入 {path.name} → doc_id={doc_id}")

    elif args.cmd == "rm":
        ok = manager.delete_document(args.doc_id)
        print(f"✅ 已删除 {args.doc_id}" if ok else f"⚠️ 未找到 {args.doc_id}")

    elif args.cmd == "replace":
        path = Path(args.path)
        if not path.exists():
            print(f"❌ 文件不存在: {path}")
            sys.exit(1)
        new_id = manager.replace_document(args.doc_id, path)
        print(f"✅ 已替换 → 新 doc_id={new_id}")


if __name__ == "__main__":
    main()
