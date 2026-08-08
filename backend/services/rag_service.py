"""RAG 对话编排:改写 → 混合检索 → 重排 → 带引用生成。

这一层是「装配车间」:把 IndexManager / 检索链 / LLM / 会话记忆
串成 answer(session_id, question) 这一个入口。API 与 CLI 都调它。
"""

import logging
import re
from functools import lru_cache

from langchain_core.messages import HumanMessage, SystemMessage

from backend.core import config
from backend.services import session_store
from backend.services.llm import get_llm
from backend.services.retrieval import (
    build_history_aware_retriever,
    build_reranked_retriever,
)

logger = logging.getLogger(__name__)

QA_SYSTEM_PROMPT = """你是「晨光科技」的企业知识助手。请严格依据下面的「参考文档」回答,规则:
1. 回答必须来自参考文档,禁止编造。
2. 每条关键信息后标注来源序号,格式如「...额度为 500 元[1]」,序号对应下方 [1][2] 等片段。
3. 文档中没有答案时,明确回答「根据现有文档无法回答」。
4. 用中文,简洁、准确、分点。

参考文档:
{context}"""


class RAGService:
    def __init__(self, manager) -> None:
        self.manager = manager
        self.llm = get_llm()
        # 整条检索链:多轮改写 → 混合检索 → 重排
        self.history_aware = build_history_aware_retriever(
            build_reranked_retriever(manager),
            llm=self.llm,
        )

    # ------------------------------------------------------------------

    def answer(self, session_id: str, question: str) -> dict:
        history = session_store.history_for(session_id)
        docs = self.history_aware.invoke({"input": question, "chat_history": history})

        if not docs:
            result = {
                "answer": "根据现有文档无法回答(未检索到相关内容)。",
                "sources": [],
                "context": "",
            }
            session_store.append(session_id, question, result["answer"])
            return result

        context = "\n\n".join(
            f"[{i}] (来源:{d.metadata.get('source', '?')}, 片段 {d.metadata.get('chunk_index', '?')})\n{d.page_content}"
            for i, d in enumerate(docs, 1)
        )
        prompt = QA_SYSTEM_PROMPT.format(context=context)
        response = self.llm.invoke(
            [SystemMessage(content=prompt), HumanMessage(content=question)]
        )
        answer = response.content if isinstance(response.content, str) else str(response.content)

        session_store.append(session_id, question, answer)
        return {
            "answer": answer,
            "context": context,
            "sources": [
                {
                    "source": d.metadata.get("source"),
                    "chunk_index": d.metadata.get("chunk_index"),
                    "doc_id": d.metadata.get("doc_id"),
                    "retrieved_by": d.metadata.get("retrieved_by"),
                    "rrf_score": d.metadata.get("rrf_score"),
                    "text": d.page_content[:200],
                }
                for d in docs
            ],
        }

    def list_documents(self) -> list[dict]:
        return self.manager.list_documents()

    def delete_document(self, doc_id: str) -> bool:
        return self.manager.delete_document(doc_id)

    def add_document(self, file_path) -> dict:
        doc_id = self.manager.add_document(file_path)
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


def extract_citations(answer: str) -> list[int]:
    """从回答里抽取引用序号,如 '[1][3]' → [1, 3]。供评估/前端使用。"""
    return [int(x) for x in re.findall(r"\[(\d+)\]", answer)]
