"""Embedding 工厂:BGE 系列中文模型,使用 sentence-transformers 直接调用。

自定义 LangChain 兼容的 Embedding 类,完全控制查询/文档的编码行为:
- 查询侧:自动加 BGE 官方 query_instruction 前缀
- 文档侧:不加指令前缀,保持原文语义

避免使用弃用的 langchain_community HuggingFaceBgeEmbeddings。
"""

import os
from typing import List

# ── Windows DLL / 线程冲突修复(必须在 import torch 前) ─────────
if os.name == "nt":
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    # ChromaDB 内部使用线程池,sentence-transformers 多线程编码会与
    # Chroma 的 sqlite3 线程冲突导致 segfault;强制单线程编码。
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")

from langchain_core.embeddings import Embeddings
from sentence_transformers import SentenceTransformer

from backend.core import config

# BGE 官方推荐的查询指令(只在编码查询时添加,文档编码不加)
_BGE_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："

_singleton: "BgeEmbedding | None" = None


class BgeEmbedding(Embeddings):
    """基于 sentence-transformers 的 BGE 中文 embedding,完全自控编码行为。

    Chroma 内部会自动区分 embed_documents(入库)和 embed_query(检索),
    本类在 embed_query 侧注入查询指令,在 embed_documents 侧保持原文。
    """

    model: SentenceTransformer

    def __init__(self, model_name: str, device: str = "cpu"):
        self.model = SentenceTransformer(model_name, device=device)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """编码文档(不加查询指令)。"""
        return self.model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        ).tolist()

    def embed_query(self, text: str) -> List[float]:
        """编码查询(加查询指令)。"""
        return self.model.encode(
            _BGE_QUERY_INSTRUCTION + text,
            normalize_embeddings=True,
            show_progress_bar=False,
        ).tolist()


def get_embedding() -> BgeEmbedding:
    """模块级单例(模型首次构造时加载 ~90MB,自动下载缓存)。"""
    global _singleton
    if _singleton is None:
        _singleton = BgeEmbedding(
            model_name=config.EMBEDDING_MODEL,
            device="cpu",
        )
    return _singleton
