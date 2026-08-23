"""集中配置:路径、模型名、开关统一在这里,改一处即可。

约定:
- 敏感信息(API key)只从环境变量 / .env 读。
- 路径一律基于本文件位置推导,不依赖运行时当前目录。
"""

import os
from pathlib import Path

# 项目根目录 = 本文件(backend/core/config.py)向上两级
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# python-dotenv 只是便利;没装也能从环境变量读
try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
except ModuleNotFoundError:
    pass

# ─── 路径 ─────────────────────────────────────────────────────────
DATA_DIR = PROJECT_ROOT / "data"
CORPUS_DIR = DATA_DIR / "corpus"
GOLDEN_DIR = DATA_DIR / "golden"
FAISS_DIR = DATA_DIR / "faiss"  # FAISS 索引目录(派生产物,由 manifest 反推可重建)
REGISTRY_DIR = DATA_DIR / "registry"
SESSION_DIR = DATA_DIR / "sessions"
EVAL_DIR = DATA_DIR / "eval"
TEXT_DIR = DATA_DIR / "texts"  # 每个文档的 chunk 文本(重建索引时重新编码,不依赖原始文件)

MANIFEST_PATH = REGISTRY_DIR / "manifest.json"

# ─── 安全 / 限流 ────────────────────────────────────────────────
# SECRET_KEY:JWT 签名 + settings.json 里 API Key 加密共用。不设则由
# backend/core/secret.py 首次启动自动生成 data/.secret(gitignore)。
SECRET_KEY = os.getenv("SECRET_KEY", "")
# 每用户每分钟可提问次数(聊天接口限流,防单用户刷爆 LLM 成本)
CHAT_RATE_LIMIT_PER_MINUTE = int(os.getenv("CHAT_RATE_LIMIT_PER_MINUTE", "30"))

# ─── LLM ──────────────────────────────────────────────────────────
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.3"))

# ─── 模型 ─────────────────────────────────────────────────────────
# 嵌入:api = 阿里百炼 DashScope(OpenAI 兼容),local = 本地 BGE
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "api").lower()
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "qwen3.7-text-embedding")
# 重排:api = 阿里百炼 text-reranker,local = 本地 bge-reranker(离线 fallback)
RERANK_PROVIDER = os.getenv("RERANK_PROVIDER", "api").lower()
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
DASHSCOPE_RERANK_MODEL = os.getenv("DASHSCOPE_RERANK_MODEL", "gte-rerank-v2")
DASHSCOPE_RERANK_URL = os.getenv(
    "DASHSCOPE_RERANK_URL",
    "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
)

# 阿里百炼 DashScope(OpenAI 兼容接口)
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
DASHSCOPE_BASE_URL = os.getenv(
    "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
)

# ─── 切分 / 检索 / 重排默认值 ────────────────────────────────────
CHUNK_SIZE = 400
CHUNK_OVERLAP = 60
RETRIEVE_TOP_N = 10       # 双路各取前 N 再 RRF 融合
RERANK_TOP_K = 4          # 重排后最终喂给 LLM 的条数
RRF_K = 60                # RRF 经典常数
HISTORY_WINDOW = 6        # 会话记忆保留最近 N 条消息

# 开关
USE_RERANK = os.getenv("USE_RERANK", "1").lower() not in ("0", "false", "no")


def validate_config() -> None:
    """启动时校验关键配置,缺 key 给出清晰中文提示。"""
    if not DEEPSEEK_API_KEY or DEEPSEEK_API_KEY.startswith("sk-your-key"):
        raise ValueError(
            "\n❌ 缺少 DEEPSEEK_API_KEY\n"
            "   1) 复制配置模板:copy .env.example .env\n"
            "   2) 编辑 .env,填入你的 DeepSeek API key\n"
            "   3) 申请地址:https://platform.deepseek.com/api_keys\n"
        )
