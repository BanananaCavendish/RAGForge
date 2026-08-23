"""检索层:混合检索(RRF)+ cross-encoder 重排 + 多轮改写,三件套。

分层:
  HybridRetriever            向量(FAISS)+ BM25 双路召回,手写 RRF 融合
  RerankRetriever            cross-encoder 把 top-N 精排到 top-K
  build_history_aware        RunnableLambda 用 LLM 把带上下文的最后一句改写成独立查询,
                             再进上面整条链(官方 create_history_aware_retriever 已在 1.x 移除)

关键设计:
  - RRF 只看「名次」不看「分数」:向量距离与 BM25 分数量纲/分布不同,直接加权不可比;
    1/(60+rank) 让两路贡献均衡,60 是业界经验常数。
  - 中文 BM25 必须 jieba 预分词:rank_bm25 按空白切分,中文整句无空格会被当成一个 token。
  - bi-encoder(向量)可预计算但精度低,做召回;cross-encoder 逐对精打精度高但贵,只做精排。
"""

import logging

import jieba
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.runnables import Runnable, RunnableLambda
from rank_bm25 import BM25Okapi

from backend.core import config

logger = logging.getLogger(__name__)


# =====================================================================
# 混合检索 + RRF
# =====================================================================


class HybridRetriever(BaseRetriever):
    """向量(FAISS)+ BM25 双路召回,手写 RRF 融合。

    corpus 必须是 FAISS 里全量 chunk 的镜像(由 IndexManager 维护),
    BM25 在内存里对这些 chunk 拟合。
    """

    vectorstore: object          # langchain_community.vectorstores.FAISS
    bm25: object                 # rank_bm25.BM25Okapi
    corpus: list[Document]
    k: int = config.RETRIEVE_TOP_N

    def _get_relevant_documents(self, query: str) -> list[Document]:
        vector_ranked = self._vector_rank(query)
        bm25_ranked = self._bm25_rank(query)
        return self._rrf_fuse(
            [vector_ranked, bm25_ranked], sources=("vector", "bm25")
        )

    def _vector_rank(self, query: str, k: int | None = None) -> list[Document]:
        k = k or self.k
        if self.vectorstore is None:  # 空知识库守卫:双路都空 → RRF 融合得空列表,不抛异常
            return []
        scored = self.vectorstore.similarity_search_with_score(query, k=k)
        return [doc for doc, _ in scored]

    def _bm25_rank(self, query: str, k: int | None = None) -> list[Document]:
        k = k or self.k
        tokens = jieba.lcut_for_search(query)
        if not self.bm25:
            return []
        return self.bm25.get_top_n(tokens, self.corpus, n=k)

    def _rrf_fuse(
        self,
        ranked_lists: list[list[Document]],
        sources: tuple[str, ...],
        top_n: int | None = None,
    ) -> list[Document]:
        """Reciprocal Rank Fusion:分数 = Σ 1/(k + rank),k=RRF_K。

        只依赖排名,不依赖各路的原始分数,天然规避量纲不一致。
        """
        scores: dict[tuple, float] = {}
        docs: dict[tuple, Document] = {}
        hits: dict[tuple, set] = {}

        for source, ranked in zip(sources, ranked_lists):
            for rank, doc in enumerate(ranked):
                key = (doc.metadata.get("doc_id"), doc.metadata.get("chunk_index"))
                scores[key] = scores.get(key, 0.0) + 1.0 / (config.RRF_K + rank + 1)
                docs[key] = doc
                hits.setdefault(key, set()).add(source)

        fused = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[
            : top_n or self.k
        ]
        out = []
        for key, score in fused:
            d = docs[key]
            d.metadata["rrf_score"] = round(score, 4)
            # 按管线顺序(vector 在前)而非字母序,前端展示更自然
            d.metadata["retrieved_by"] = [s for s in sources if s in hits[key]]
            out.append(d)
        return out


def build_hybrid_retriever(manager, k: int = config.RETRIEVE_TOP_N) -> HybridRetriever:
    """从 IndexManager 构建混合检索器(corpus/BM25 由 manager 维护)。"""
    return HybridRetriever(
        vectorstore=manager.vectorstore,
        bm25=manager.bm25,
        corpus=manager.all_docs,
        k=k,
    )


class _EmptyRetriever(BaseRetriever):
    """空库占位检索器:知识库为空时返回空结果,避免调用方崩在 None 上。"""

    def _get_relevant_documents(self, query: str) -> list[Document]:
        return []


def build_vector_retriever(manager, k: int = config.RETRIEVE_TOP_N) -> BaseRetriever:
    """纯向量检索器(评估消融用,对比混合检索的增益)。空库返回空检索器。"""
    if manager.vectorstore is None:
        return _EmptyRetriever()
    return manager.vectorstore.as_retriever(search_kwargs={"k": k})


# =====================================================================
# 重排(手写,RAG 链路核心之一)
# =====================================================================


class RerankRetriever(BaseRetriever):
    """混合检索(top-k 粗召回)→ 重排器精排(到 top-K)。

    为什么不用 LangChain 的 ContextualCompressionRetriever?
    它在 LangChain 1.x 已移除;且手写 wrapper 逻辑更透明:
      bi-encoder(向量)可预计算但精度低 → 做召回;
      cross-encoder 逐对精打、精度高但贵 → 只做精排。

    优雅降级:重排器(API/本地)故障时记 warning 并按混合检索原序返回,
    重排问题绝不拖垮对话。
    """

    base: BaseRetriever
    top_k: int = config.RERANK_TOP_K

    def _get_relevant_documents(self, query: str) -> list[Document]:
        docs = self.base.invoke(query)
        if not docs:
            return []

        try:
            from backend.services.reranker import get_reranker

            scores = get_reranker().rank(query, [d.page_content for d in docs])
        except Exception as e:  # noqa: BLE001 —— 重排故障降级
            logger.warning("重排器调用失败,按混合检索原序返回: %s", e)
            return docs[: self.top_k]

        ranked = sorted(
            zip(docs, scores), key=lambda x: x[1], reverse=True
        )[: self.top_k]

        out = []
        for doc, score in ranked:
            doc.metadata["rerank_score"] = round(float(score), 4)
            out.append(doc)
        return out


def build_reranked_retriever(
    manager, top_k: int = config.RERANK_TOP_K, k: int = config.RETRIEVE_TOP_N
) -> BaseRetriever:
    """混合检索(top-k 粗召回)→ cross-encoder 精排(到 top-K)。

    是否启用重排读运行时设置(前端「设置」页可改),不再读启动时的 env 常量。
    """
    from backend.core import settings

    hybrid = build_hybrid_retriever(manager, k=k)
    if not settings.load_settings().rerank.enabled:
        return hybrid
    return RerankRetriever(base=hybrid, top_k=top_k)


# =====================================================================
# 多轮查询改写
# =====================================================================

def build_history_aware_retriever(retriever: BaseRetriever, llm) -> Runnable:
    """把 retriever(已含混合检索+重排)包成多轮对话检索器。

    invoke({"input": question, "chat_history": history})
    → (若有历史)LLM 改写 → 双路召回 → RRF 融合 → cross-encoder 精排 → 返回 top 文档。

    为什么不用官方 create_history_aware_retriever?它在 LangChain 1.x 已被移除
    (langchain.chains / langchain.retrievers 顶层模块都不存在了),且包装一层官方组件
    反而不好讲实现。这里显式用 RunnableLambda 包「改写→检索」两步,逻辑完全透明。
    """
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

    from backend.services.prompts import CONDENSE_PROMPT

    prompt = ChatPromptTemplate.from_messages(
        [
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", CONDENSE_PROMPT),
        ]
    )
    condense_chain = prompt | llm | StrOutputParser()

    def _condense_and_retrieve(inputs: dict) -> list[Document]:
        question, history = inputs["input"], inputs["chat_history"]
        if history:  # 有历史才改写;首轮直接检索原句
            question = condense_chain.invoke(
                {"input": question, "chat_history": history}
            )
            logger.info("改写后查询: %s", question)
        return retriever.invoke(question)

    return RunnableLambda(_condense_and_retrieve)
