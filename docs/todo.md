# 项目进度与下一步

## ✅ 已验证(2026-08-08)

- **嵌入**:已从本地 `bge-small-zh-v1.5` 切换为**阿里百炼 `qwen3.7-text-embedding`**(API,dim=1024)。
  自实现 `DashScopeEmbedding`(直接调 OpenAI 兼容接口)——因为 langchain-openai 会对输入
  做 tiktoken 分词,而该模型期望原文字符串。切嵌入后已重建 FAISS 索引。

- **P1 语料**:`generate_corpus.py` 生成 5 文档、4 种格式(PDF/MD/DOCX/HTML),中文正常。
- **P2 建库**:FAISS 索引 5 文档 / 12 chunk,调试查询命中正确文档。
- **P3 检索**:`demo_retrieval.py` 三路对比通过;hybrid 能补足 vector 单路遗漏。
- **P4 对话**:`demo_chat.py` 多轮 + 查询改写 + 引用标注验证通过:
  - 问「报销要什么材料」→ 回答列材料并标注 `[1]`;
  - 追问「那额度上限呢?」→ 改写为独立查询,命中差旅文档,给出具体额度。
- **P5 API**:文档管理增/删/查(201→200)通过;`/api/chat` 两轮对话带记忆通过。
- **P6 评估**:15 题 golden 全跑通,报告写入 `data/eval/report.json`。

## ⚠️ 已知取舍

1. **重排默认关闭(`USE_RERANK=0`)**:`BAAI/bge-reranker-v2-m3`(~2.3GB)在国内镜像
   hf-mirror 上大文件下载失败(huggingface.co 直连被墙),暂无法启用。代码路径
   (`RerankRetriever`)已写好并走通逻辑,仅缺模型权重。挂了梯子后重跑:
   `python -c "from sentence_transformers import CrossEncoder; CrossEncoder('BAAI/bge-reranker-v2-m3', device='cpu')"` 即可下载。
   **替代方案**:阿里百炼有 `text-reranker` 重排 API(国内直连),可仿照 `DashScopeEmbedding`
   自实现 `DashScopeReranker`,不用本地模型。
2. **评估区分度不足**:当前小语料(5 文档)下三路 recall 全顶格(1.00),无法体现
   混合检索 / 重排的增量价值。

## 🔭 下一步(可选,提升简历含金量)

- **扩展语料**:增加 3~5 个「语义易混淆」的干扰文档(如"费用报销流程指南"与
  "差旅报销制度"语义相近但内容不同),让 vector 会误命中、hybrid 靠 BM25 精确词纠偏,
  制造 recall@k 的上升曲线 → 评估表出现「vector 0.87 → hybrid 0.97 → rerank 1.00」。
- **启用重排**:网络通后下载 reranker,`USE_RERANK=1`,展示 cross-encoder 精排增益。
- **前端打磨**:聊天 UI 展示来源卡片与 rerank 分数。
