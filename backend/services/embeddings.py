"""Embedding 工厂:支持两路接入,`get_embedding()` 统一返回 Embeddings 接口。

1. **api(默认)**:阿里百炼 DashScope `qwen3.7-text-embedding`,OpenAI 兼容接口。
   - 优点:国内直连、无需本地模型、维度高(语义更强)、不占磁盘。
   - 注意:API 型嵌入不接受 BGE 的 query_instruction 前缀,查询/文档统一编码。
2. **local**:本地 `BAAI/bge-small-zh-v1.5`(sentence-transformers),离线可跑。
   - BGE 官方推荐查询侧加指令前缀,文档侧不加,本类已实现。

切换:改 `.env` 的 `EMBEDDING_PROVIDER`。换嵌入后必须重建索引
(`python scripts/build_index.py`,向量空间变了旧索引作废)。
"""

import json
import os
import ssl
import urllib.error
import urllib.request
from typing import List

# ── Windows DLL / 线程冲突修复(必须在 import torch 前) ─────────
if os.name == "nt":
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")

from langchain_core.embeddings import Embeddings

from backend.core import config


# =====================================================================
# 本地 BGE(local provider)
# =====================================================================

# BGE 官方推荐的查询指令(只在编码查询时添加,文档编码不加)
_BGE_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："

_bge_singleton: "BgeEmbedding | None" = None


class BgeEmbedding(Embeddings):
    """基于 sentence-transformers 的 BGE 中文 embedding,本地离线运行。

    查询侧注入 BGE 查询指令,文档侧保持原文。
    """

    def __init__(self, model_name: str, device: str = "cpu"):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name, device=device)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self.model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        ).tolist()

    def embed_query(self, text: str) -> List[float]:
        return self.model.encode(
            _BGE_QUERY_INSTRUCTION + text,
            normalize_embeddings=True,
            show_progress_bar=False,
        ).tolist()


def _get_bge() -> Embeddings:
    global _bge_singleton
    if _bge_singleton is None:
        _bge_singleton = BgeEmbedding(model_name=config.EMBEDDING_MODEL, device="cpu")
    return _bge_singleton


# =====================================================================
# 阿里百炼 API(api provider)
# =====================================================================


class DashScopeEmbedding(Embeddings):
    """直接调 DashScope OpenAI 兼容接口,查询与文档统一编码(无指令前缀)。

    为什么不用 langchain_openai.OpenAIEmbeddings?它会对输入做 tiktoken 分词,
    把原文拆成 token id 数组发给 API;而 DashScope 的 qwen3.7-text-embedding
    期望的是原文字符串,会报 `input.contents is neither str nor list of str`。
    这里自实现,`input` 直接传原文,行为完全可控。
    """

    def __init__(self, model: str, api_key: str, base_url: str):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._ctx = ssl.create_default_context()

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._call(texts)

    def embed_query(self, text: str) -> List[float]:
        return self._call([text])[0]

    def _call(self, texts: List[str]) -> List[List[float]]:
        body = json.dumps({"model": self.model, "input": texts}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/embeddings",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60, context=self._ctx) as r:
                data = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(
                f"DashScope 嵌入失败: HTTP {e.code} {e.read().decode()[:300]}"
            ) from e
        return [item["embedding"] for item in data["data"]]


_dashscope_singleton: Embeddings | None = None


def _get_dashscope() -> Embeddings:
    """DashScope OpenAI 兼容嵌入。查询与文档统一编码(API 型无指令前缀)。"""
    global _dashscope_singleton
    if _dashscope_singleton is None:
        if not config.DASHSCOPE_API_KEY:
            raise ValueError(
                "\n❌ 缺少 DASHSCOPE_API_KEY(EMBEDDING_PROVIDER=api)\n"
                "   在 .env 填入阿里百炼 API key:https://bailian.console.aliyun.com/\n"
            )
        _dashscope_singleton = DashScopeEmbedding(
            model=config.EMBEDDING_MODEL,
            api_key=config.DASHSCOPE_API_KEY,
            base_url=config.DASHSCOPE_BASE_URL,
        )
    return _dashscope_singleton


# =====================================================================
# 工厂
# =====================================================================

_embedding: Embeddings | None = None


def get_embedding() -> Embeddings:
    """模块级单例:按 EMBEDDING_PROVIDER 选择实现,首次调用时构造。"""
    global _embedding
    if _embedding is None:
        if config.EMBEDDING_PROVIDER == "local":
            _embedding = _get_bge()
        else:
            _embedding = _get_dashscope()
    return _embedding
