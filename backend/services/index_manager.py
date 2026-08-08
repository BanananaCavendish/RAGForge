"""IndexManager —— 索引的生命周期管理,也是「增量更新」的核心。

真相来源(Source of Truth):
  manifest.json   记录了「当前有哪些文档、每个文档多少 chunk」
派生索引(Derived):
  FAISS(向量)     用于向量召回
  BM25(内存)      用于关键词召回

任何增删改都收敛到这个单例:API 上传、CLI 管理、建库脚本,全部走它。

设计说明:
  采用 FAISS 而非 ChromaDB——在 Anaconda Python 3.11 + Windows 环境下,
  ChromaDB 的 SQLite 层与 PyTorch 的内存分配冲突导致 segfault。
  FAISS 是纯 C++ 向量检索库,无 SQLite 依赖,稳定且更快。
  代价:FAISS 不支持按 metadata 删除 chunk,删除文档时需要全量重建索引
  (小语料成本可忽略,几十个文档毫秒级)。

增量更新的关键设计:
  1. doc_id = sha256(文件内容)  → 内容寻址:重复导入同一文件幂等(no-op)
  2. 增:嵌入 → FAISS 合并 + BM25 重建 + manifest 更新
  3. 删:过滤 all_docs → FAISS 重建 + BM25 重建 + manifest 清理
"""

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path

import jieba
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from rank_bm25 import BM25Okapi

from backend.core import config
from backend.ingestion.ingest import ingest_document
from backend.services.embeddings import get_embedding

logger = logging.getLogger(__name__)


class IndexManager:
    def __init__(self) -> None:
        self.faiss_path = config.CHROMA_DIR / "faiss_index"  # 复用路径名不变
        self.manifest_path = config.MANIFEST_PATH
        self.manifest: dict = self._load_manifest()
        self.all_docs: list[Document] = []
        self.bm25: BM25Okapi | None = None
        self.vectorstore: FAISS | None = None
        self._refresh_from_store()

    # ─── 初始化 / 重建 ─────────────────────────────────────────────

    def _refresh_from_store(self) -> None:
        """启动时从 FAISS 持久文件加载,或从 manifest 重建。

        FAISS 支持 save_local / load_local,但增量更新后需显式保存。
        若持久文件不存在且有 manifest → 说明索引从未保存过(首次建库),
        后续 add_document 会自动创建。
        """
        if self.manifest and self.faiss_path.exists():
            self.vectorstore = FAISS.load_local(
                str(self.faiss_path),
                get_embedding(),
                allow_dangerous_deserialization=True,
            )
            # 从 FAISS 导出全量 chunk 重建 all_docs(用于 BM25 与混合检索)
            # FAISS 内部 docstore 存储了 Document 对象
            self.all_docs = list(self.vectorstore.docstore._dict.values())
            self.rebuild_bm25()
            logger.info(
                "索引就绪(FAISS): %d 个 chunk, %d 个文档",
                len(self.all_docs), len(self.manifest),
            )
        elif self.manifest:
            # manifest 存在但 FAISS 文件丢失 → 标记需重建
            logger.warning("FAISS 索引文件丢失,请重新建库: python scripts/build_index.py")
        else:
            logger.info("索引就绪: 0 个 chunk, 0 个文档")

    def rebuild_bm25(self) -> None:
        """中文 BM25:语料与查询两侧都必须 jieba 预分词(rank_bm25 按空白切分)。"""
        if not self.all_docs:
            self.bm25 = None
            return
        self.bm25 = BM25Okapi(
            [jieba.lcut_for_search(d.page_content) for d in self.all_docs]
        )

    def _save_faiss(self) -> None:
        """持久化 FAISS 索引到磁盘。"""
        if self.vectorstore is not None:
            self.faiss_path.parent.mkdir(parents=True, exist_ok=True)
            self.vectorstore.save_local(str(self.faiss_path))

    # ─── 增删改 ────────────────────────────────────────────────────

    def add_document(self, file_path: str | Path) -> str:
        """导入单个文档。内容寻址幂等:同一文件重复导入返回同一个 doc_id。"""
        file_path = Path(file_path)
        doc_id = self._content_hash(file_path)

        if doc_id in self.manifest:
            logger.info("跳过重复导入: %s (doc_id=%s)", file_path.name, doc_id)
            return doc_id

        chunks = ingest_document(file_path, doc_id)

        if self.vectorstore is None:
            # 首次入库:用这批 chunk 创建 FAISS 索引
            self.vectorstore = FAISS.from_documents(chunks, get_embedding())
        else:
            self.vectorstore.add_documents(chunks)

        self.all_docs += chunks
        self.rebuild_bm25()
        self._save_faiss()

        self.manifest[doc_id] = {
            "filename": file_path.name,
            "fmt": file_path.suffix.lstrip(".").lower(),
            "num_chunks": len(chunks),
            "added_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._save_manifest()
        logger.info("已导入: %s (%d chunks, doc_id=%s)", file_path.name, len(chunks), doc_id)
        return doc_id

    def delete_document(self, doc_id: str) -> bool:
        """按 doc_id 删除文档及其全部 chunk。

        FAISS 不支持按 metadata 删除,故从 all_docs 中过滤掉目标 chunk 后
        全量重建 FAISS 索引(小语料成本可忽略,毫秒级)。
        """
        if doc_id not in self.manifest:
            return False

        removed = [d for d in self.all_docs if d.metadata.get("doc_id") == doc_id]
        self.all_docs = [d for d in self.all_docs if d.metadata.get("doc_id") != doc_id]
        self.rebuild_bm25()

        if self.all_docs:
            self.vectorstore = FAISS.from_documents(self.all_docs, get_embedding())
        else:
            self.vectorstore = None

        self._save_faiss()
        self.manifest.pop(doc_id, None)
        self._save_manifest()
        logger.info("已删除: doc_id=%s (%d chunks)", doc_id, len(removed))
        return True

    def replace_document(self, doc_id: str, file_path: str | Path) -> str:
        """先删旧版本,再导入新文件。新内容 → 新 doc_id。"""
        self.delete_document(doc_id)
        return self.add_document(file_path)

    # ─── 查询接口(供检索器使用) ──────────────────────────────────

    def get_document(self, doc_id: str) -> dict | None:
        return self.manifest.get(doc_id)

    def list_documents(self) -> list[dict]:
        return [
            {"doc_id": did, **info}
            for did, info in sorted(
                self.manifest.items(), key=lambda kv: kv[1]["added_at"]
            )
        ]

    # ─── 内部工具 ──────────────────────────────────────────────────

    @staticmethod
    def _content_hash(file_path: Path) -> str:
        return hashlib.sha256(file_path.read_bytes()).hexdigest()[:12]

    def _load_manifest(self) -> dict:
        if self.manifest_path.exists():
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        return {}

    def _save_manifest(self) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(
            json.dumps(self.manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
