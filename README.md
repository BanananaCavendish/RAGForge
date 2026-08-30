<p align="center">
  <h1 align="center">RAGForge</h1>
  <p align="center">企业级检索增强问答引擎 · 为答案锻造出处</p>
  <p align="center">
    <img alt="Python" src="https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white">
    <img alt="LangChain" src="https://img.shields.io/badge/LangChain-1.x-1C3C3C?logo=langchain&logoColor=white">
    <img alt="Framework" src="https://img.shields.io/badge/FastAPI-0.110-009688?logo=fastapi&logoColor=white">
    <img alt="Vector Store" src="https://img.shields.io/badge/Vector%20Store-FAISS%20%2B%20BM25-blue">
    <img alt="Embedding" src="https://img.shields.io/badge/Embedding-qwen3.7--text--embedding-purple">
  </p>
  <p align="center">
    <b>登录鉴权</b> · <b>多用户隔离</b> · <b>混合检索 + RRF</b> · <b>文件级引用</b> · <b>SSE 流式对话</b> · <b>异步文档摄取</b>
  </p>
</p>

---

**RAGForge** —— 企业级检索增强问答引擎,为答案锻造出处。

上传 PDF / Word / Markdown / HTML 文档,用自然语言提问,回答自动标注 `[n]` **文件编号来源**——每个文件一个编号,来源面板按文件分组,悬浮即可查看片段摘要。支持多轮对话上下文、SSE 流式输出、文档级权限隔离,并通过黄金问答集量化召回率与回答质量。前端为 **RAGFlow 风格多视图界面**(暗色紫罗兰、零构建、移动端适配)。

> 🚀 **免费在线体验**:请访问 **[https://ragforge.zeabur.app](https://ragforge.zeabur.app) 体验我们的云服务** —— 已内置演示知识库,注册账号即可直接问答(演示实例,语料为虚构,数据可能被重置)。

## 目录

- [特性](#特性)
- [快速开始](#快速开始)
- [云服务体验](#云服务体验)
- [部署到云端](#部署到云端)
- [使用方法](#使用方法)
- [架构](#架构)
- [评估结果](#评估结果)
- [项目结构](#项目结构)
- [配置项](#配置项)
- [技术栈](#技术栈)
- [与原始模板的差异](#与原始模板的差异)
- [踩坑记录](#踩坑记录)
- [路线图](#路线图)

## 特性

| 能力 | 说明 | 核心代码 |
|---|---|---|
| 🔐 登录鉴权 | scrypt 哈希密码 + JWT,首个注册用户为管理员 | `backend/core/security.py`、`backend/api/auth.py` |
| 👥 多用户与权限 | 文档级 ACL:语料库全员可见、私有文档仅本人+被分享者、admin 全量 | `backend/db/repositories.py` |
| 🔑 密钥加密 | `settings.json` 里的 API key 用 Fernet 加密落盘,磁盘无明文 | `backend/core/settings.py` |
| 📄 多格式接入 | PDF / Word / Markdown / HTML 一键盘入库 | `backend/ingestion/` |
| ⏳ 异步摄取 | 上传即返回 202 + task_id,后台线程建索引,前端轮询进度 | `backend/api/routes/documents.py` |
| 🔍 混合检索 | 向量 + BM25 双路召回,手写 **RRF 融合**(只看排名不看分数) | `backend/services/retrieval.py` |
| 🎯 Cross-Encoder 重排 | 粗召回 top-10 精排到 top-4(可选,`USE_RERANK`) | 同上 |
| 💬 SSE 流式对话 | 逐 token 输出 + 结束事件,消息持久化到 SQLite(重启不丢) | `backend/api/routes/chat.py` |
| 🛡️ 限流 | 每用户每分钟对话上限,超限 429 + Retry-After | `backend/services/rate_limit.py` |
| 🩺 健康检查 | `GET /healthz` 免登录,返回版本/索引/DB 状态(Docker 探活用) | `backend/api/routes/health.py` |
| 🧪 评估体系 | golden QA + recall@k / MRR / 忠实度 / 引用准确率 | `backend/evaluation/` |
| 🎨 RAGFlow 风格 UI | 暗色紫罗兰主题、左侧图标导航、对话/知识库双视图、响应式(移动端底部标签栏) | `frontend/static/` |
| 📎 文件级引用 | 每个文件一个顺序编号 `[n]`,来源面板按文件分组展示,悬浮查看片段摘要 | `backend/services/rag_service.py`、`frontend/static/app.js` |
| 🖱️ 交互细节 | 引用悬浮气泡、文档状态徽章、拖拽上传、流式光标、一键复制、确认弹窗 | `frontend/static/app.js` |

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
start.bat                            # Web 界面 → http://127.0.0.1:8001/（固定 8001，避免与 RatingGuard 的 8000 冲突）
```

## 云服务体验

免费在线演示部署于 Zeabur 免费档:**[https://ragforge.zeabur.app](https://ragforge.zeabur.app)**

1. 打开链接,点「注册」创建账号(**第一个注册的用户是管理员**);
2. 直接提问,试试这些示例问题:
   - 「差旅报销需要准备哪些材料?」
   - 「密码口令有什么要求?」
   - 「年休假怎么算?」
3. 回答自动标注 `[n]` 文件级引用,右侧来源面板按文件分组展示。

> ⚠️ **演示说明**:实例已内置 10 份虚构企业文档(晨光科技),语料为脚本生成、仅供学习演示;未挂持久化卷,实例重建后用户与对话记录可能清空;任何访客都可注册并消耗部署者的 LLM 配额,请留意成本。部署与安全细节见下文 [部署到云端](#部署到云端)。

## 部署到云端

本项目可直接部署到任意支持 Docker 的平台。线上演示跑在 **Zeabur** 免费档,流程:

1. **推送并关联仓库**:代码推到 GitHub 后,在 Zeabur 控制台「新建项目 → 添加服务 → 从 GitHub 导入仓库」,Zeabur 自动识别 Dockerfile 并构建(构建期会预生成语料 + 本地 BGE 索引)。
2. **服务端口**:网络设置把端口设为 `8001`(镜像内已 `EXPOSE 8001`)。
3. **环境变量**(与镜像内建索引的嵌入配置保持一致):

| 变量 | 值 | 说明 |
|---|---|---|
| `EMBEDDING_PROVIDER` | `local` | 必须与构建期一致,否则前端提示「需要重建索引」 |
| `EMBEDDING_MODEL` | `BAAI/bge-small-zh-v1.5` | 本地 BGE 嵌入,免嵌入 API key |
| `USE_RERANK` | `0` | 演示档不跑重排,省内存、免外部请求失败降级 |
| `DEEPSEEK_API_KEY` | `sk-xxx` | **必填**,对话模型 key(申请:https://platform.deepseek.com/api_keys) |
| `SECRET_KEY` | `openssl rand -base64 32` | JWT 签名 + API key 加密,务必改为随机值并保持稳定 |
| `CHAT_RATE_LIMIT_PER_MINUTE` | `10` | 演示实例压低每用户限流,控制成本 |

4. **域名**:Zeabur 生成 `https://<服务名>.zeabur.app` 公网地址,也可绑定自己的域名(自带 HTTPS)。

**为什么镜像里已带索引?** Dockerfile 构建阶段会重新生成 10 份虚构语料并调用 `build_index.py`,用本地 BGE 建好 FAISS + BM25 索引烤进镜像——云实例一启动即可检索,无需部署后再上传文档或配嵌入 key。索引的 `embedding_sig` 指纹必须与运行时环境变量一致;改了嵌入配置,需在前端「设置」页手动重建索引。

**公网部署须知**:
- 公网必须设置强 `SECRET_KEY`,并确保 HTTPS(Zeabur 域名默认自带)。
- 「第一个注册的用户是管理员」的引导逻辑在公网实例上意味着**谁先注册谁就是 admin**——演示场景建议自己先注册;若要对外开放注册,后续可加「注册开关」或预置 admin 账号。
- 未挂持久化卷时,运行时数据(用户、对话、上传文档)在实例重建后丢失;生产环境应挂卷(`./data:/app/data`,见 docker-compose)。

## 使用方法

### Web 界面

```bash
start.bat              # 推荐：双击运行，固定 8001 端口
# 或手动指定端口：
# uvicorn backend.main:app --host 127.0.0.1 --port 8001 --reload
```

浏览器打开 `http://127.0.0.1:8001/`,先用「注册」创建账号(**第一个注册的用户是管理员**,只有管理员能进「设置」页改模型配置 / 重建索引),登录后支持聊天问答与文档管理。API 文档在 `/docs`(Swagger)。

> **端口说明**：`127.0.0.1:8000` 被同机的 RatingGuard 后端占用，RAG 固定使用 `8001`。若 `8001` 也被占用，用 `--port` 换成其他端口即可。

### REST API

除 `/healthz` 外全部需登录(`Authorization: Bearer <token>`);除 `/api/auth/*` 外均为用户级隔离。

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/auth/register` | 注册(首个用户自动成为管理员) |
| `POST` | `/api/auth/login` | 登录,返回 JWT |
| `GET` | `/api/auth/me` | 当前用户信息 |
| `POST` | `/api/chat` | 多轮问答,`{question, session_id}`,返回带来源引用的回答 |
| `POST` | `/api/chat/stream` | SSE 流式问答:逐 token 输出 + 结束事件 |
| `GET` / `POST` | `/api/sessions` | 会话列表 / 新建会话 |
| `GET` | `/api/sessions/{id}/messages` | 会话消息历史 |
| `DELETE` | `/api/sessions/{id}` | 删除会话 |
| `GET` | `/api/documents` | 列出当前用户可见文档 |
| `POST` | `/api/documents` | 上传文档 → `202` + `task_id`(异步摄取) |
| `GET` | `/api/documents/tasks` | 上传任务进度(admin 见全部,否则见自己的) |
| `PUT` | `/api/documents/{doc_id}` | 替换文档 |
| `DELETE` | `/api/documents/{doc_id}` | 删除文档(admin / 所有者) |
| `GET` | `/api/documents/{doc_id}/preview` | 预览文档前 5 个片段 |
| `GET` | `/api/settings` | 运行时设置(仅 admin,key 已掩码) |
| `GET` | `/healthz` | 健康检查(免登录) |

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
    H --> I[回答 + [n] 文件级来源]
```

一次问答的数据流:`POST /api/chat` → 取会话历史 → (有历史则 LLM 改写最后一句) → 向量 + BM25 双路召回 → RRF 融合 → (可选)cross-encoder 精排 → 按文件分组编号喂给 LLM → LLM 依据上下文带文件级引用生成 → 回写会话记忆。

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
│   ├── api/                       # 路由(schemas / chat / documents / auth / sessions / health)
│   │   └── deps.py                # get_current_user / get_admin_user 依赖
│   ├── core/                      # config / settings(密钥加密) / security(scrypt+JWT) / secret
│   ├── db/                        # SQLite:schema + database(连接管理) + repositories(数据访问)
│   ├── services/                  # 检索链 / 索引 / 会话存储 / 嵌入 / LLM / 限流
│   ├── ingestion/                 # 多格式 loader + 中文分块
│   └── evaluation/                # 指标计算 + LLM-as-judge
├── frontend/static/               # 三件套 index.html + app.css + app.js:RAGFlow 风格多视图 SPA(暗色紫罗兰 · 左侧导航 · 对话/知识库双视图)
├── scripts/                       # 语料 / 建库 / demo / 评估 / 冒烟
├── data/
│   ├── corpus/                    # 生成的虚构语料(提交)
│   ├── golden/                    # 手写 golden QA(评估基准)
│   ├── app.db                     # SQLite 库(用户/会话/文档/ACL,gitignore)
│   ├── .secret                    # 加密密钥(自动生成,gitignore)
│   └── chroma/ registry/ eval/    # 派生产物(gitignore)
├── Dockerfile / docker-compose.yml
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
| `SECRET_KEY` | 自动生成到 `data/.secret` | JWT 签名 + API key 加密的主密钥 |
| `CHAT_RATE_LIMIT_PER_MINUTE` | `30` | 每用户每分钟对话请求上限(超限 429) |

## 技术栈

| 层 | 选型 |
|---|---|
| 语言 / 框架 | Python 3.11 · LangChain 1.x · FastAPI |
| LLM | DeepSeek(OpenAI 兼容接口) |
| 嵌入 | 阿里百炼 `qwen3.7-text-embedding`(API,自动按 20 条/批)/ 本地 `bge-small-zh-v1.5` |
| 向量库 | FAISS(cosine) |
| 稀疏检索 | `rank_bm25` + `jieba` 中文分词 |
| 重排(可选) | `bge-reranker-v2-m3`(cross-encoder) |
| 持久化 | SQLite(`data/app.db`,WAL)+ Fernet 密钥加密 |
| 认证 | scrypt 哈希 + pyjwt(JWT HS256) |
| 前端 | 原生 JS 三文件多视图 SPA,零构建;暗色紫罗兰 RAGFlow 风格 |

## 与原始模板的差异

本项目是在开源教程项目 **RAG From Zero**(无框架手写实现,配套 10 章教程)的基础上重构与扩展的。保留了原项目的核心设计思路——向量 + BM25 双路召回与 RRF 融合、cross-encoder 重排、查询改写、带引用生成——其余部分做了如下改动:

| 方面 | 原始模板(RAG From Zero) | 本项目 |
|---|---|---|
| 技术框架 | 核心代码全手写,不依赖框架 | 基于 LangChain 1.x 组织检索链 / 记忆 / 调用 |
| 向量库 | ChromaDB(本地持久化) | FAISS(`faiss-cpu`),解决 Windows 下 Chroma 段错误 |
| 嵌入模型 | 本地 `bge-m3`(~2GB) | 阿里百炼 `qwen3.7-text-embedding`(API)或本地 `bge-small-zh-v1.5` |
| 文档格式 | 仅 PDF(保险语料) | PDF / Word / Markdown / HTML(企业知识语料) |
| 多轮对话 | 单轮问答 | 会话记忆 + LLM 查询改写,支持多轮上下文 |
| 增量更新 | 只有全量建库 | 内容寻址 `doc_id` 幂等,增 / 删 / 替换文档不重建全量索引 |
| 评估体系 | 冒烟测试(验证装配逻辑) | golden QA + recall@k / MRR / 忠实度 / 引用准确率,输出报告 |
| 接口形态 | 命令行脚本 | FastAPI REST API + Web 聊天界面 |
| 前端形态 | 命令行 / 简单页面 | RAGFlow 风格产品级多视图 UI(暗色紫罗兰、对话/知识库双视图) |
| 引用粒度 | 片段级 `[n]`(片段顺序编号) | 文件级 `[n]`(每文件一个编号,来源按文件分组展示) |

## 踩坑记录

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
11. **DashScope 嵌入单次上限 20 条**——删除文档 / 重建索引会一次传几百个 chunk,超限报 `400 InvalidParameter(batch size > 20)`;`DashScopeEmbedding.embed_documents` 已按 20 条/批自动分批再拼接。FakeEmbeddings 测不出这个,需 mock urlopen 验证请求数(见 `test_embeddings.py`)。
12. **SQLite 连接别在事务内读新写入**——同一 `with` 块内另开连接读不到未提交的 INSERT(返回 None → 级联 TypeError);写入后要读,先退出事务再开连接(见 `backend/db/database.py::connect`)。
13. **uvicorn `--reload` 双实例会抢 8001 端口**——后台已有一个实例时再双击 start.bat,会出现两个 reloader 同时监听同一端口,改完代码仍可能被旧实例响应。用 `netstat -ano | findstr 8001` 排查,只保留一个实例。

## 路线图

- [x] **登录鉴权 + 多用户隔离**(Tier 0)——scrypt + JWT + 文档级 ACL + 检索层 pre-filter
- [x] **异步摄取 / 会话持久化 / SSE 流式 / 限流**(Tier 1)——SQLite + 后台任务 + 流式输出 + 每用户限流
- [x] **生产部署**(Tier 0)——`/healthz` + Dockerfile + docker-compose + 密钥加密 + 日志轮转
- [ ] **扩展语料**(3~5 个语义易混淆的干扰文档),制造 recall@k 上升曲线,让消融表有区分度
- [ ] **启用重排**——自实现阿里百炼 `text-reranker` API(仿 `DashScopeEmbedding`,已完成降级逻辑)
- [x] 前端展示 rrf / rerank 分数徽章
- [ ] **模型设置入口放开给普通用户**(只读查看配置,仅 admin 可改 / 重建索引)

> 免责声明:所有企业语料为脚本生成的虚构内容,仅供学习演示。
