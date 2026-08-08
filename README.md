<p align="center">
  <h1 align="center">企业知识助手 RAG</h1>
  <p align="center">基于 LangChain 1.x 的企业级 RAG 知识问答系统 · 简历项目</p>
  <p align="center">
    <img alt="Python" src="https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white">
    <img alt="LangChain" src="https://img.shields.io/badge/LangChain-1.x-1C3C3C?logo=langchain&logoColor=white">
    <img alt="Framework" src="https://img.shields.io/badge/FastAPI-0.110-009688?logo=fastapi&logoColor=white">
    <img alt="Vector Store" src="https://img.shields.io/badge/Vector%20Store-FAISS%20%2B%20BM25-blue">
    <img alt="Embedding" src="https://img.shields.io/badge/Embedding-qwen3.7--text--embedding-purple">
  </p>
  <p align="center">
    <b>多格式接入</b> · <b>混合检索 + RRF 融合</b> · <b>带引用多轮对话</b> · <b>增量文档管理</b> · <b>评估体系</b>
  </p>
</p>

---

一个**能跑、能量化、讲得清**的 RAG 企业知识助手:上传 PDF / Word / Markdown / HTML 文档,即可用自然语言问答,回答自动标注 `[1][2]` 来源引用,支持多轮对话上下文,并通过黄金问答集量化召回率与回答质量。

> 设计目标:不只是"跑通",而是每一个环节都能在面试中讲清楚原理与取舍(混合检索为什么用 RRF、bi-encoder vs cross-encoder、增量更新如何保证幂等、LLM-as-judge 如何可控)。

## 目录

- [特性](#特性)
- [快速开始](#快速开始)
- [使用方法](#使用方法)
- [架构](#架构)
- [评估结果](#评估结果)
- [项目结构](#项目结构)
- [配置项](#配置项)
- [技术栈](#技术栈)
- [踩坑记录](#踩坑记录)
- [面试准备](#面试准备)
- [路线图](#路线图)

## 特性

| 能力 | 说明 | 核心代码 |
|---|---|---|
| 📄 多格式接入 | PDF / Word / Markdown / HTML 一键盘入库 | `backend/ingestion/` |
| 🔍 混合检索 | 向量 + BM25 双路召回,手写 **RRF 融合**(只看排名不看分数) | `backend/services/retrieval.py` |
| 🎯 Cross-Encoder 重排 | 粗召回 top-10 精排到 top-4(可选,`USE_RERANK`) | 同上 |
| 💬 带引用多轮对话 | 回答标注 `[1][2]` 来源 + LLM 查询改写 + 会话记忆 | `backend/services/rag_service.py` |
| 📈 增量文档管理 | 内容寻址 `doc_id` 幂等,增/删/替换不重建全量索引 | `backend/services/index_manager.py` |
| 🧪 评估体系 | golden QA + recall@k / MRR / 忠实度 / 引用准确率 | `backend/evaluation/` |

## 快速开始

### 环境要求

- Python 3.11(Windows / Linux / macOS 均可)
- 两个 API key:DeepSeek(对话生成)、阿里百炼(嵌入)

### 安装

```bash
python -m venv .venv
source .venv/Scripts/activate      # Windows Git Bash;macOS/Linux 用 source .venv/bin/activate
pip install -r requirements.txt    # 国内可加 -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 配置

```bash
cp .env.example .env
# 编辑 .env,填入两个 key:
#   DEEPSEEK_API_KEY=sk-xxx        # https://platform.deepseek.com/api_keys
#   DASHSCOPE_API_KEY=sk-xxx       # https://bailian.console.aliyun.com/
```

嵌入默认走阿里百炼 API(`qwen3.7-text-embedding`),无需下载本地模型;若想用本地 BGE,将 `EMBEDDING_PROVIDER` 改为 `local` 并 `export HF_ENDPOINT=https://hf-mirror.com`。

### 构建索引并运行

```bash
python scripts/generate_corpus.py    # 生成 5 个虚构企业文档(4 种格式)
python scripts/build_index.py        # 分块 → 向量化 → 建 FAISS + BM25 索引

python scripts/demo_chat.py          # 命令行多轮对话
uvicorn backend.main:app --reload    # Web 界面 → http://127.0.0.1:8000/
```

## 使用方法

### Web 界面

```bash
uvicorn backend.main:app --reload
```

浏览器打开 `http://127.0.0.1:8000/`,支持聊天问答与文档管理。API 文档在 `/docs`(Swagger)。

### REST API

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/chat` | 多轮问答,`{question, session_id}`,返回带来源引用的回答 |
| `GET` | `/api/documents` | 列出已入库文档 |
| `POST` | `/api/documents` | 上传文档(增量入库) |
| `PUT` | `/api/documents/{doc_id}` | 替换文档 |
| `DELETE` | `/api/documents/{doc_id}` | 删除文档 |

### 命令行脚本

| 脚本 | 作用 |
|---|---|
| `scripts/generate_corpus.py` | 生成虚构企业语料(员工手册 / 报销制度 / 安全策略 / FAQ / 产品手册) |
| `scripts/build_index.py` | 全量建库(幂等,已入库跳过) |
| `scripts/demo_retrieval.py` | 三路检索对比:vector / hybrid / hybrid+rerank |
| `scripts/demo_chat.py` | 命令行多轮对话,展示查询改写与引用标注 |
| `scripts/manage_docs.py` | CLI 增/删/替换文档 |
| `scripts/run_eval.py` | 跑完整评估,输出指标表到 `data/eval/report.json` |

## 架构

```mermaid
flowchart LR
    A[多格式文档] --> B[Loader 分派]
    B --> C[中文分块 + overlap]
    C --> D[(FAISS 向量库)]
    C --> E[BM25 内存索引<br/>jieba 分词]
    D --> F[混合检索 RRF 融合]
    E --> F
    F --> G[Cross-Encoder 重排<br/>可选]
    G --> H[LLM 带引用生成]
    H --> I[回答 + [1][2] 来源]
```

一次问答的数据流:`POST /api/chat` → 取会话历史 → (有历史则 LLM 改写最后一句) → 向量 + BM25 双路召回 → RRF 融合 → (可选)cross-encoder 精排 → LLM 依据上下文带引用生成 → 回写会话记忆。

完整架构与增量更新设计见 [docs/architecture.md](docs/architecture.md)。

## 评估结果

> 在 15 题 golden QA 上运行,详见 [data/eval/report.json](data/eval/report.json)

| 策略 | recall@3 | recall@5 | recall@10 | MRR | 忠实度 | 引用准确率 |
|---|---|---|---|---|---|---|
| vector | 1.00 | 1.00 | 1.00 | 0.967 | — | — |
| hybrid | 1.00 | 1.00 | 1.00 | 0.967 | — | — |
| **hybrid+rerank** | 1.00 | 1.00 | 1.00 | 0.967 | 1.00 | 1.00 |

> ⚠️ 当前为小语料(5 文档)下的结果:每类问题都能被三路稳定命中,recall 顶格、区分度不足。要看到「混合检索/重排带来提升」的上升曲线,需扩展语料并加入**语义易混淆的干扰文档**——见 [路线图](#路线图)。

## 项目结构

```
.
├── backend/
│   ├── main.py                    # FastAPI 入口:路由 + 静态页挂载
│   ├── api/                       # 路由(schemas / chat / documents)
│   ├── core/config.py             # 集中配置(路径 / 模型 / 开关,读 .env)
│   ├── services/                  # 检索链 / 索引管理 / 会话记忆 / 嵌入 / LLM
│   ├── ingestion/                 # 多格式 loader + 中文分块
│   └── evaluation/                # 指标计算 + LLM-as-judge
├── frontend/static/               # 单页聊天 + 文档管理界面(原生 JS)
├── scripts/                       # 语料 / 建库 / demo / 评估
├── data/
│   ├── corpus/                    # 生成的虚构语料(提交)
│   ├── golden/                    # 手写 golden QA(评估基准)
│   └── chroma/ registry/ eval/    # 派生产物(gitignore)
├── docs/architecture.md           # 架构设计文档
├── requirements.txt
└── .env.example                   # 配置模板
```

## 配置项

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `DEEPSEEK_API_KEY` | — | **必填**,DeepSeek 对话模型 key |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | OpenAI 兼容端点 |
| `LLM_MODEL` | `deepseek-chat` | 对话模型名 |
| `EMBEDDING_PROVIDER` | `api` | `api`(百炼)/ `local`(本地 BGE) |
| `EMBEDDING_MODEL` | `qwen3.7-text-embedding` | 嵌入模型名 |
| `DASHSCOPE_API_KEY` | — | 阿里百炼嵌入 key |
| `RERANKER_MODEL` | `BAAI/bge-reranker-v2-m3` | 重排模型(本地) |
| `USE_RERANK` | `0` | 是否启用 cross-encoder 重排 |

## 技术栈

| 层 | 选型 |
|---|---|
| 语言 / 框架 | Python 3.11 · LangChain 1.x · FastAPI |
| LLM | DeepSeek(OpenAI 兼容接口) |
| 嵌入 | 阿里百炼 `qwen3.7-text-embedding`(API)/ 本地 `bge-small-zh-v1.5` |
| 向量库 | FAISS(cosine) |
| 稀疏检索 | `rank_bm25` + `jieba` 中文分词 |
| 重排(可选) | `bge-reranker-v2-m3`(cross-encoder) |
| 前端 | 原生 JS 单页,无构建工具 |

## 踩坑记录

> 面试时讲这些,比背八股更能体现实战能力。

1. **中文 BM25 必须 jieba 预分词**——`rank_bm25` 按空白切分,中文整句无空格会被当成一个 token,BM25 直接失效。
2. **RRF 用排名不用分数**——向量距离与 BM25 分数量纲/分布不同,直接加权不可比;`1/(60+rank)` 只看名次。
3. **FAISS 按文档删 = 过滤 chunk 后整体重建**——`vectorstore.delete` 只支持按 chunk id 删;按文档删更省心的做法是 `all_docs` 过滤该文档的 chunk 后 `FAISS.from_documents` 重建(小语料毫秒级,顺带重训 BM25)。
4. **ChromaDB 在 Windows + Anaconda 偶发段错误(Exit 139)**——`add_documents` 时进程直接崩;换 `faiss-cpu` 一行解决。
5. **LangChain 0.3 → 1.x 迁移**——`ContextualCompressionRetriever` 已移除,重排手写 `BaseRetriever` 包装;`create_history_aware_retriever` 也被移除,多轮改写用 `RunnableLambda` 自实现;Chroma 独立成 `langchain_chroma` 包。
6. **阿里百炼嵌入别用 langchain-openai**——它会对输入做 tiktoken 分词,把原文拆成 token id 发给 API,而 `qwen3.7-text-embedding` 期望原文字符串。自实现 `DashScopeEmbedding` 直接传原文。
7. **LLM-as-judge 要可控**——`temperature=0` + 结构化输出 + 带 reason 字段 + 金标人工复核;DeepSeek 不支持 `response_format=json_schema`,需直接解析文本 JSON。
8. **torch 别乱升**——Windows + Anaconda 下 torch 2.13 启动即 `WinError 1114`,固定 `torch==2.6.0`;CPU 环境 `OMP_NUM_THREADS=1` 防多进程内存爆炸。
9. **Windows 控制台是 GBK**——打印中文/emoji 报 `UnicodeEncodeError`,脚本开头 `sys.stdout.reconfigure(encoding="utf-8")`;管道喂中文还要同步 reconfigure stdin。
10. **换嵌入必须重建索引**——不同嵌入模型维度/语义空间不同,旧 FAISS 索引作废,先删 `data/chroma data/registry` 再 `build_index.py`。

## 面试准备

- **为什么混合检索?** 向量抓语义、BM25 抓精确词(政策编号、数字、专有名词),互补。
- **为什么还要重排?** bi-encoder 可预计算但精度低;cross-encoder 逐对精打精度高但贵,所以只做精排(top-10 → top-4)。
- **多轮怎么处理?** LLM 依据历史改写最后一句,再进混合检索;历史截断最近 6 条。刻意不用 `RunnableWithMessageHistory`,自己管 `session_store` 更透明。
- **增量更新怎么做?** manifest 是真相源,内容寻址 `doc_id` 保幂等;FAISS 删文档 = 过滤 chunk 后重建,BM25 同步重建。
- **忠实度 vs 引用准确率?** 前者判整体是否被支持,后者逐条判 `[i]` 是否真支撑那句陈述。

## 路线图

- [ ] **扩展语料**(3~5 个语义易混淆的干扰文档),制造 recall@k 上升曲线,让消融表有区分度
- [ ] **启用重排**——本地 reranker 模型在国内镜像下载受限;替代方案是自实现阿里百炼 `text-reranker` API(仿 `DashScopeEmbedding`)
- [ ] 前端展示来源卡片与 rerank 分数

> 免责声明:所有企业语料为脚本生成的虚构内容,仅供学习演示。
