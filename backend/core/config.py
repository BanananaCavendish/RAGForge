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
CHROMA_DIR = DATA_DIR / "chroma"
REGISTRY_DIR = DATA_DIR / "registry"
SESSION_DIR = DATA_DIR / "sessions"
EVAL_DIR = DATA_DIR / "eval"

MANIFEST_PATH = REGISTRY_DIR / "manifest.json"

# ─── LLM ──────────────────────────────────────────────────────────
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.3"))

# ─── 模型 ─────────────────────────────────────────────────────────
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")

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
