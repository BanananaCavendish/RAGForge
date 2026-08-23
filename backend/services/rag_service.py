"""RAG 对话编排:改写 → 混合检索 → 重排 → 带引用生成。

这一层是「装配车间」:把 IndexManager / 检索链 / LLM / 会话记忆
串成 answer(session_id, question) 这一个入口。API 与 CLI 都调它。
"""

import logging
import re
from functools import lru_cache

from langchain_core.messages import HumanMessage, SystemMessage

from backend.services import session_store
from backend.services.llm import get_llm
from backend.services.prompts import QA_SYSTEM_PROMPT
from backend.services.retrieval import (
    build_history_aware_retriever,
    build_reranked_retriever,
)

logger = logging.getLogger(__name__)


class RAGService:
    def __init__(self, manager, llm=None) -> None:
        self.manager = manager
        # llm 可注入:测试传 Fake LLM 即可离线跑通整条链路,不碰真实 DeepSeek API
        self.llm = llm or get_llm()
        # 整条检索链:多轮改写 → 混合检索 → 重排
        self.history_aware = build_history_aware_retriever(
            build_reranked_retriever(manager),
            llm=self.llm,
        )

    # ------------------------------------------------------------------

    def _retrieve(
        self, session_id: str, question: str, user_id: int | None, allowed_doc_ids: set[str] | None
    ) -> list:
        """多轮改写 → 混合检索 → 重排,再按权限过滤。

        allowed_doc_ids=None 表示不限制(管理员/CLI/评估);否则只保留
        当前用户可访问的文档,别把别人私有文档的内容拼进 prompt。
        """
        history = session_store.store.history_for(session_id, user_id)
        docs = self.history_aware.invoke({"input": question, "chat_history": history})
        return self._filter_docs(docs, allowed_doc_ids)

    @staticmethod
    def _filter_docs(docs: list, allowed_doc_ids: set[str] | None) -> list:
        """按 ACL 过滤检索结果;None 表示不过滤(admin/CLI/评估)。"""
        if allowed_doc_ids is None:
            return docs
        return [d for d in docs if d.metadata.get("doc_id") in allowed_doc_ids]

    @staticmethod
    def _build_context(docs: list) -> str:
        return "\n\n".join(
            f"[{i}] (来源:{d.metadata.get('source', '?')}, 片段 {d.metadata.get('chunk_index', '?')})\n{d.page_content}"
            for i, d in enumerate(docs, 1)
        )

    @staticmethod
    def _build_sources(docs: list) -> list[dict]:
        return [
            {
                "source": d.metadata.get("source"),
                "chunk_index": d.metadata.get("chunk_index"),
                "doc_id": d.metadata.get("doc_id"),
                "retrieved_by": d.metadata.get("retrieved_by"),
                "rrf_score": d.metadata.get("rrf_score"),
                "rerank_score": d.metadata.get("rerank_score"),
                "text": d.page_content[:200],
            }
            for d in docs
        ]

    def answer(
        self,
        session_id: str,
        question: str,
        user_id: int | None = None,
        allowed_doc_ids: set[str] | None = None,
    ) -> dict:
        """单轮回答(非流式)。CLI / 评估 / 测试走这里;前端用 answer_stream。"""
        docs = self._retrieve(session_id, question, user_id, allowed_doc_ids)

        if not docs:
            result = {
                "answer": "根据现有文档无法回答(未检索到相关内容)。",
                "sources": [],
                "context": "",
            }
            session_store.store.append(session_id, user_id, question, result["answer"])
            return result

        context = self._build_context(docs)
        prompt = QA_SYSTEM_PROMPT.format(context=context)
        response = self.llm.invoke(
            [SystemMessage(content=prompt), HumanMessage(content=question)]
        )
        answer = response.content if isinstance(response.content, str) else str(response.content)

        session_store.store.append(session_id, user_id, question, answer)
        return {
            "answer": answer,
            "context": context,
            "sources": self._build_sources(docs),
        }

    def answer_stream(
        self,
        session_id: str,
        question: str,
        user_id: int | None = None,
        allowed_doc_ids: set[str] | None = None,
    ):
        """流式回答(SSE):逐 token 产出,结尾带完整答案与来源。

        事件类型:
          {"type": "token", "text": "..."}   模型逐字输出
          {"type": "done", "answer", "sources", "context"}  结束
          {"type": "answer", ...}            未检索到内容的整段回答
        """
        docs = self._retrieve(session_id, question, user_id, allowed_doc_ids)

        if not docs:
            answer = "根据现有文档无法回答(未检索到相关内容)。"
            session_store.store.append(session_id, user_id, question, answer)
            yield {"type": "answer", "answer": answer, "sources": [], "context": ""}
            return

        context = self._build_context(docs)
        prompt = QA_SYSTEM_PROMPT.format(context=context)
        full = ""
        for chunk in self.llm.stream(
            [SystemMessage(content=prompt), HumanMessage(content=question)]
        ):
            text = chunk.content if isinstance(chunk.content, str) else ""
            full += text
            yield {"type": "token", "text": text}

        session_store.store.append(session_id, user_id, question, full)
        yield {
            "type": "done",
            "answer": full,
            "context": context,
            "sources": self._build_sources(docs),
        }

    def list_documents(self) -> list[dict]:
        return self.manager.list_documents()

    def delete_document(self, doc_id: str) -> bool:
        return self.manager.delete_document(doc_id)

    def add_document(self, file_path, source_name: str | None = None) -> dict:
        doc_id = self.manager.add_document(file_path, source_name=source_name)
        info = self.manager.get_document(doc_id)
        return {"doc_id": doc_id, **info}


@lru_cache(maxsize=1)
def get_manager() -> "IndexManager":
    """索引单例:仅文档管理用,不依赖 DeepSeek key。

    与 get_service 分开,让「文档管理 API」在没配 key 时也能用。
    """
    from backend.services.index_manager import IndexManager

    return IndexManager()


@lru_cache(maxsize=1)
def get_service():
    """完整 RAG 服务单例(需 DeepSeek key):索引 + 检索链 + LLM + 记忆。"""
    return RAGService(get_manager())


def invalidate_services() -> None:
    """索引重建后调用:清掉 service/manager 单例,下次请求按新索引重建。"""
    get_manager.cache_clear()
    get_service.cache_clear()


def ensure_index_ready() -> None:
    """嵌入模型变更后未重建索引时,向量维度不匹配会让检索崩溃,提前给出明确指引。"""
    from backend.core import settings

    if settings.needs_reindex():
        raise RuntimeError("嵌入模型已变更,请先在「设置」页重建索引后再继续。")


def extract_citations(answer: str) -> list[int]:
    """从回答里抽取引用序号,如 '[1][3]' → [1, 3]。

    用途:评估侧校验引用准确率、前端高亮引用来源。注意 run_eval 用的是
    judge.py 自己的正则实现;本函数供测试与前端链路复用。
    """
    return [int(x) for x in re.findall(r"\[(\d+)\]", answer)]
