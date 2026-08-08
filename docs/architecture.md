# 架构设计

## 总体流程

```mermaid
flowchart LR
    subgraph 接入侧[Ingestion · 增量更新]
        A[多格式文档<br/>PDF / Word / MD / HTML] --> B[Loader 分派]
        B --> C[中文感知分块<br/>句读优先 + overlap]
        C --> D[(FAISS 向量库)]
        D --> E[Manifest 注册表<br/>doc_id → 文件信息]
        C --> F[BM25 内存索引<br/>jieba 分词]
    end

    subgraph 问答侧[Online Q&A]
        Q[用户问题] --> G[多轮查询改写<br/>LLM 依据历史]
        G --> H[混合检索<br/>向量 + BM25]
        H --> I[RRF 融合]
        I --> J[Cross-Encoder 重排]
        J --> K[生成 · 带引用<br/>LLM]
        K --> A1[回答 + 引用来源]
    end

    E --> H
    F --> H
    D --> H
    A1 --> E2[会话记忆<br/>最近 N 条]
    E2 --> G

    subgraph 评估侧[Evaluation]
        L[Golden QA 集] --> M[检索消融<br/>recall@k / MRR]
        M --> N[LLM-as-judge<br/>忠实度 / 引用准确率]
        N --> O[(report.json)]
    end
```

## 分层职责

| 层 | 文件 | 职责 |
|---|---|---|
| API | `backend/api/routes/*` | HTTP 入口:`/api/chat`、`/api/documents` 增删查 |
| 服务 | `backend/services/rag_service.py` | 编排:改写→检索→重排→生成→记忆 |
| 服务 | `backend/services/retrieval.py` | HybridRetriever(RRF)、重排、多轮改写 |
| 服务 | `backend/services/index_manager.py` | 索引生命周期 + 增量更新(真相源 = manifest) |
| 服务 | `backend/services/session_store.py` | 会话记忆(内存 + 截断) |
| 接入 | `backend/ingestion/*` | 多格式加载、中文分块、打元数据 |
| 评估 | `backend/evaluation/*` | 检索指标 + LLM-as-judge |

## 数据流(一次问答)

1. `POST /api/chat {session_id, question}`
2. `rag_service.answer()` 取该会话最近 6 条消息
3. 若有历史,`RunnableLambda` 用 LLM(CONDENSE_PROMPT)把最后一句改写成独立查询(官方 `create_history_aware_retriever` 已在 LangChain 1.x 移除,自己包一层更透明)
4. 改写后的查询同时进向量路(FAISS)与关键词路(BM25, jieba 分词)
5. 两条路各取 top-10,手写 RRF 融合:`score = Σ 1/(60 + rank)`
6. 融合后 top-10 交给 cross-encoder 精排到 top-4(可选,`USE_RERANK=0` 时跳过)
7. 带引用生成:上下文按 `[1][2]…` 编号,LLM 必须标注来源
8. 回答与来源写回会话记忆,返回前端

## 增量更新的设计

- **真相来源**:`data/registry/manifest.json`——记录每个 `doc_id` 的文件名、格式、chunk 数。
- **内容寻址**:`doc_id = sha256(文件内容)[:12]`,重复导入幂等,文件变化自然产生新 doc_id。
- **删除**:Chroma 只支持按 id 删 → `collection.get(where={"doc_id": ...})` 拿 ids → `delete(ids)`。
- **BM25**:静态拟合,不支持增量 → 变更后全量重建(小语料毫秒级)。
