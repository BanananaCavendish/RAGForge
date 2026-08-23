"""Reranker 工厂:支持两路接入,`get_reranker()` 统一返回带 `rank(query, documents)` 的对象。

1. **api(默认)**:阿里百炼 DashScope `gte-rerank-v2` 文本重排。
   - 为什么换 API:本地 bge-reranker-v2-m3(约 2.3GB)国内镜像下载失败,正是
     `USE_RERANK` 默认关闭的根因。API 版免下载、中文效果好、不占磁盘。
   - 一次请求批量传全部候选,按 `index` 字段把分数还原到输入顺序(缺失补 0.0)。
2. **local**:本地 `BAAI/bge-reranker-v2-m3`(sentence-transformers CrossEncoder),离线可跑。

切换:前端「设置」页改(写 data/settings.json),或改 `.env` 的 `RERANK_PROVIDER`。
配置以运行时设置(settings.py)为准。
"""

import json
import os
import ssl
import urllib.error
import urllib.request

# ── Windows DLL / 线程冲突修复(必须在 import torch 前) ─────────
if os.name == "nt":
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")

from backend.core import settings


# =====================================================================
# 阿里百炼 API(api provider)
# =====================================================================


class DashScopeReranker:
    """调 DashScope 文本重排原生端点,`rank(query, documents)` 返回与输入对齐的分数。

    为什么不用 langchain 的 reranker:与 DashScopeEmbedding 同理,直接调原生端点,
    行为完全可控、无额外 SDK 依赖、接口风格与项目现有自实现一致。
    """

    def __init__(self, model: str, api_key: str, endpoint: str):
        self.model = model
        self.api_key = api_key
        self.endpoint = endpoint
        self._ctx = ssl.create_default_context()

    def rank(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        body = json.dumps(
            {
                "model": self.model,
                "input": {"query": query, "documents": documents},
                "parameters": {"top_n": len(documents), "return_documents": False},
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint,
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
                f"DashScope 重排失败: HTTP {e.code} {e.read().decode()[:300]}"
            ) from e

        # 结果按相关度降序返回;用 index 字段还原到输入顺序,未返回的补 0.0
        scores = [0.0] * len(documents)
        for item in data["output"]["results"]:
            idx = item["index"]
            if 0 <= idx < len(documents):
                scores[idx] = float(item["relevance_score"])
        return scores


_dashscope_reranker_singleton: "DashScopeReranker | None" = None


def _get_dashscope() -> DashScopeReranker:
    global _dashscope_reranker_singleton
    if _dashscope_reranker_singleton is None:
        rerank = settings.load_settings().rerank
        api_key = settings.effective_rerank_api_key()  # 重排 key 缺省复用嵌入 key
        if not api_key:
            raise ValueError(
                "\n❌ 缺少重排模型的 API Key(RERANK_PROVIDER=api)\n"
                "   请在网页「设置」页填入,或写入 .env 的 DASHSCOPE_API_KEY\n"
            )
        _dashscope_reranker_singleton = DashScopeReranker(
            model=rerank.model,
            api_key=api_key,
            endpoint=rerank.base_url,
        )
    return _dashscope_reranker_singleton


# =====================================================================
# 本地 BGE(local provider)
# =====================================================================


class LocalReranker:
    """本地 cross-encoder 重排(离线 fallback),模型懒加载避免启动开销。"""

    def __init__(self, model_name: str, device: str = "cpu"):
        self.model_name = model_name
        self.device = device
        self._model = None

    def rank(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name, device=self.device)
        return [
            float(s) for s in self._model.predict([(query, d) for d in documents])
        ]


_local_reranker_singleton: "LocalReranker | None" = None


def _get_local() -> LocalReranker:
    global _local_reranker_singleton
    if _local_reranker_singleton is None:
        model_name = settings.load_settings().rerank.model
        _local_reranker_singleton = LocalReranker(model_name=model_name)
    return _local_reranker_singleton


# =====================================================================
# 工厂
# =====================================================================

_reranker = None


def get_reranker():
    """按运行时设置(settings.json 覆盖 .env)选择重排器,模块级单例(懒构造)。"""
    global _reranker
    if _reranker is None:
        if settings.load_settings().rerank.provider == "local":
            _reranker = _get_local()
        else:
            _reranker = _get_dashscope()
    return _reranker


def invalidate_reranker() -> None:
    """配置变更后清掉单例,下次 get_reranker() 按新配置重建。"""
    global _reranker, _dashscope_reranker_singleton, _local_reranker_singleton
    _reranker = None
    _dashscope_reranker_singleton = None
    _local_reranker_singleton = None
