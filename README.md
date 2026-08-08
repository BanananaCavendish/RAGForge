# 企业知识助手 RAG · 简历项目

> 一个**能跑、能量化、讲得清**的 RAG 企业知识助手,基于 LangChain 1.x。
> 多格式接入 · 混合检索与重排 · 带引用多轮对话 · 增量文档管理 · 评估体系

---

## ✨ 亮点

| 能力 | 说明 | 代码 |
|---|---|---|
| 多格式接入 | PDF / Word / Markdown / HTML 一键盘入库 | `backend/ingestion/` |
| 混合检索 | 向量 + BM25 双路召回,手写 **RRF 融合** | `backend/services/retrieval.py` |
| Cross-Encoder 重排 | bge-reranker 把粗召回 top-10 精排到 top-4 | 同上 |
| 带引用多轮对话 | 回答标注 `[1][2]` 来源 + 会话记忆 | `backend/services/rag_service.py` |
| 增量文档管理 | 增/删/替换文档,不用全量重建索引 | `backend/services/index_manager.py` |
| 评估体系 | golden QA + recall@k / MRR / 忠实度 / 引用准确率 | `backend/evaluation/` |

## 📈 评估结果

> 在 15 题 golden QA 上运行,详见 [report.json](data/eval/report.json)

| 策略 | recall@3 | recall@5 | recall@10 | MRR | 忠实度 | 引用准确率 |
|---|---|---|---|---|---|---|
| vector | _待回填_ | _待回填_ | _待回填_ | _待回填_ | — | — |
| hybrid | _待回填_ | _待回填_ | _待回填_ | _待回填_ | — | — |
| **hybrid+rerank** | _待回填_ | _待回填_ | _待回填_ | _待回填_ | _待回填_ | _待回填_ |

## 🚀 快速开始

```bash
# 1. 环境
python -m venv .venv && source .venv/Scripts/activate   # Windows Git Bash
pip install -r requirements.txt                          # 国内可加 -i https://pypi.tuna.tsinghua.edu.cn/simple

# 2. 配置(国内请先设置 huggingface 镜像,否则模型可能下不动)
export HF_ENDPOINT=https://hf-mirror.com
cp .env.example .env && # 填入 DEEPSEEK_API_KEY

# 3. 生成语料 + 建库
python scripts/generate_corpus.py
python scripts/build_index.py

# 4. 跑起来
python scripts/demo_retrieval.py      # 三路检索对比(vector / hybrid / rerank)
python scripts/demo_chat.py           # 命令行多轮对话
python scripts/run_eval.py            # 评估(需要 API key)
uvicorn backend.main:app --reload     # Web 界面 → http://127.0.0.1:8000/
```

## 🏗️ 架构

```mermaid
flowchart LR
    A[多格式文档] --> B[Loader 分派]
    B --> C[中文分块 + overlap]
    C --> D[(Chroma 向量库)]
    C --> E[BM25 内存索引<br/>jieba 分词]
    D --> F[混合检索 RRF 融合]
    E --> F
    F --> G[Cross-Encoder 重排]
    G --> H[LLM 带引用生成]
    H --> I[回答 + [1][2] 来源]
```

完整架构见 [docs/architecture.md](docs/architecture.md)。

## 🛠️ 我踩过的坑(面试重点)

1. **中文 BM25 必须 jieba 预分词**——`rank_bm25` 按空白切分,中文整句无空格会被当成一个 token,BM25 直接失效。
2. **RRF 用排名不用分数**——向量距离与 BM25 分数量纲/分布不同,直接加权不可比;`1/(60+rank)` 只看名次。
3. **Chroma 只支持按 id 删**——按文档删要先 `collection.get(where={"doc_id": ...})` 拿 ids 再 `delete(ids)`;入库必须用显式 id。
4. **LangChain 0.3 → 1.x 迁移**——重排器导入路径变了、`create_history_aware_retriever` 收敛到 `langchain.chains`、Chroma 独立成 `langchain_chroma` 包。
5. **LLM-as-judge 要可控**——`temperature=0` + 结构化输出 + 带 reason 字段 + 金标人工复核。

## 🔧 目录结构

```
backend/           FastAPI + RAG 服务 + 评估
frontend/static/   单页聊天界面(无构建工具)
scripts/           语料/建库/检索对比/对话/管理/评估
data/
  corpus/          生成的虚构企业语料(提交)
  golden/          手写 golden QA(提交,评估基准)
  chroma/ registry/ eval/   派生产物(不提交)
```

## 🧭 面试准备

- **为什么混合检索?** 向量抓语义、BM25 抓精确词(政策编号、数字、专有名词),互补。
- **为什么还要重排?** bi-encoder 可预计算但精度低;cross-encoder 逐对精打精度高但贵,所以只做精排。
- **多轮怎么处理?** LLM 依据历史改写最后一句,再进混合检索;历史截断最近 6 条。
- **增量更新怎么做?** manifest 是真相源,内容寻址 doc_id 保幂等,Chroma 按 where 删,BM25 变更后重建。
- **忠实度 vs 引用准确率?** 前者判整体是否被支持,后者逐条判 `[i]` 是否真支撑那句陈述。

## 📦 版本

- Python 3.11 · LangChain 1.x(`langchain-community` 0.3.x,官方不升 1.0)
- LLM: DeepSeek(OpenAI 兼容) · Embedding: `BAAI/bge-small-zh-v1.5` · 重排: `BAAI/bge-reranker-v2-m3`
- 向量库: ChromaDB(cosine)

> 免责声明:所有企业语料为脚本生成的虚构内容,仅供学习演示。
