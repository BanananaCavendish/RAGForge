"""运行时设置:模型与 API Key 的「客户可配置」层。

配置来源,自高到低覆盖(任一字段都是「有值则覆盖」):
  1. data/settings.json  —— 用户在「设置」页保存的配置(持久化,.gitignore)
  2. .env / 环境变量     —— 出厂默认(部署/开发时改的配置)
  3. 代码内建默认值      —— 兜底

所以:换环境或改 .env 后,没被用户改过的字段自动跟随;用户改过的字段
永远记住(settings.json 覆盖 env)。

密钥安全:
- API Key 落盘前用 Fernet 加密(密钥来自 data/.secret 或环境变量 SECRET_KEY),
  磁盘上的 settings.json 不含任何明文 key;内存中始终是解密后的明文供调用。
- GET /api/settings 只返回掩码(sk-****abcd)+ 是否已配置;PUT 时才接收明文。

索引联动:
- 切嵌入模型 → 向量空间/维度变 → 旧索引作废,必须重建。
- 用 index.embedding_sig 记录「当前索引是用哪套嵌入配置构建的」,
  needs_reindex() = 当前嵌入配置 != 构建索引时的嵌入配置。
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path

from cryptography.fernet import Fernet
from pydantic import BaseModel, Field

from backend.core import config
from backend.core.secret import get_secret_key

logger = logging.getLogger(__name__)

SETTINGS_FILE_NAME = "settings.json"

# ─── 可选模型清单(前端下拉 + 后端校验共用)────────────────────
EMBEDDING_MODELS = {
    "api": [
        "qwen3.7-text-embedding",
        "text-embedding-v4",
        "text-embedding-v3",
        "text-embedding-v2",
    ],
    "local": ["BAAI/bge-small-zh-v1.5", "BAAI/bge-large-zh-v1.5"],
}
RERANK_MODELS = {
    "api": ["gte-rerank-v2", "gte-rerank-v1"],
    "local": ["BAAI/bge-reranker-v2-m3", "BAAI/bge-reranker-base"],
}
# LLM 提供方:base_url 为空表示自定义(前端让用户填)
LLM_PROVIDERS = [
    {
        "id": "deepseek",
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
    {
        "id": "dashscope",
        "label": "阿里百炼(DashScope)",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen-plus", "qwen-turbo", "qwen-max"],
    },
    {
        "id": "openai",
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o-mini", "gpt-4o"],
    },
    {"id": "custom", "label": "自定义(OpenAI 兼容)", "base_url": "", "models": []},
]


# ─── 设置模型 ────────────────────────────────────────────────────


class LLMSettings(BaseModel):
    provider: str = "deepseek"
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"
    api_key: str = ""
    temperature: float = 0.3


class EmbeddingSettings(BaseModel):
    provider: str = "api"  # api=阿里百炼,local=本地 BGE
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model: str = "qwen3.7-text-embedding"
    api_key: str = ""


class RerankSettings(BaseModel):
    enabled: bool = True
    provider: str = "api"
    base_url: str = "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
    model: str = "gte-rerank-v2"
    api_key: str = ""  # 留空则复用嵌入模型的 key(与 .env 时代行为一致)


class IndexState(BaseModel):
    embedding_sig: str = ""  # 构建当前索引所用的嵌入配置指纹
    rebuilding: bool = False
    progress: int = 0  # 0-100
    last_rebuilt_at: str = ""
    last_rebuild_error: str = ""


class RuntimeSettings(BaseModel):
    llm: LLMSettings = Field(default_factory=LLMSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    rerank: RerankSettings = Field(default_factory=RerankSettings)
    index: IndexState = Field(default_factory=IndexState)


# ─── 磁盘读写 ────────────────────────────────────────────────────


def settings_file() -> Path:
    """动态读 config.DATA_DIR:测试 monkeypatch 路径时能跟随。"""
    return config.DATA_DIR / SETTINGS_FILE_NAME


def _env_defaults() -> RuntimeSettings:
    """从 .env / config 构造出厂默认;settings.json 未覆盖的字段用它。"""
    dashscope_key = config.DASHSCOPE_API_KEY or ""
    return RuntimeSettings(
        llm=LLMSettings(
            provider="deepseek",
            base_url=config.DEEPSEEK_BASE_URL,
            model=config.LLM_MODEL,
            api_key=config.DEEPSEEK_API_KEY or "",
            temperature=config.LLM_TEMPERATURE,
        ),
        embedding=EmbeddingSettings(
            provider=config.EMBEDDING_PROVIDER,
            base_url=config.DASHSCOPE_BASE_URL,
            model=config.EMBEDDING_MODEL,
            api_key=dashscope_key,
        ),
        rerank=RerankSettings(
            enabled=config.USE_RERANK,
            provider=config.RERANK_PROVIDER,
            base_url=config.DASHSCOPE_RERANK_URL,
            model=(
                config.DASHSCOPE_RERANK_MODEL
                if config.RERANK_PROVIDER != "local"
                else config.RERANKER_MODEL
            ),
            api_key=dashscope_key,
        ),
    )


def _overlay(base: RuntimeSettings, saved: dict) -> None:
    """把 settings.json 中的字段合并进 base(有值即覆盖,None 跳过)。"""
    for section in ("llm", "embedding", "rerank", "index"):
        data = saved.get(section)
        if not isinstance(data, dict):
            continue
        target = getattr(base, section)
        for field_name, value in data.items():
            if field_name in type(target).model_fields and value is not None:
                setattr(target, field_name, value)


# ─── API Key 落盘加密(Fernet)──────────────────────────────────
# 磁盘上的 key 统一存为 "enc:<token>";内存里始终是解密后的明文。
# 换 SECRET_KEY 会导致旧密文解不开 —— 按「未配置」处理并打错误日志提示重填。

_ENC_PREFIX = "enc:"
_KEY_FIELDS = ("llm", "embedding", "rerank")


def _cipher() -> Fernet:
    return Fernet(get_secret_key().encode("utf-8"))


def _encrypt_key(value: str) -> str:
    if not value or value.startswith(_ENC_PREFIX):
        return value
    return _ENC_PREFIX + _cipher().encrypt(value.encode("utf-8")).decode("utf-8")


def _decrypt_key(value: str) -> str:
    if value and value.startswith(_ENC_PREFIX):
        try:
            return _cipher().decrypt(value[len(_ENC_PREFIX) :].encode("utf-8")).decode("utf-8")
        except Exception as e:  # noqa: BLE001 —— 密钥不匹配时如实报警,前端能重填
            logger.error("API Key 解密失败(可能 SECRET_KEY 已更换): %s", e)
            return ""
    return value


def _load_from_disk() -> RuntimeSettings:
    base = _env_defaults()
    path = settings_file()
    if path.exists():
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            _overlay(base, saved)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("settings.json 解析失败,回退 .env 默认: %s", e)
    # 落盘的是密文 → 读进内存前解回明文
    for section in _KEY_FIELDS:
        model = getattr(base, section)
        model.api_key = _decrypt_key(model.api_key)
    if base.index.rebuilding:
        # 上次进程在重建中途被杀 → 残留的「重建中」状态作废,否则前端会一直轮询
        logger.warning("检测到残留的索引重建状态,已复位(重建未完成,请重新触发)")
        base.index.rebuilding = False
        base.index.progress = 0
    _seed_index_sig(base)
    return base


_cache: RuntimeSettings | None = None


def load_settings() -> RuntimeSettings:
    """返回当前生效设置(内存缓存)。写操作后调用 reload_settings() 失效。"""
    global _cache
    if _cache is None:
        _cache = _load_from_disk()
    return _cache


def reload_settings() -> None:
    global _cache
    _cache = None


def save_settings(settings: RuntimeSettings | None = None) -> None:
    """持久化到磁盘并刷新缓存。落盘前把 API Key 加密为 enc:<token>。"""
    global _cache
    settings = settings or load_settings()
    data = settings.model_dump()
    for section in _KEY_FIELDS:
        if data.get(section, {}).get("api_key"):
            data[section]["api_key"] = _encrypt_key(data[section]["api_key"])
    path = settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _cache = settings


def update_settings(patch: dict) -> RuntimeSettings:
    """合并并校验前端提交的配置(局部更新,未提交的字段保持不变)。

    patch 形如 {"embedding": {"provider": "local", "model": "...", "api_key": "..."}}。
    校验 provider 合法性;api_key 传 "" 表示清除,不传表示保留。
    """
    settings = load_settings()
    _overlay(settings, patch)
    _validate(settings)
    save_settings(settings)
    return settings


def _validate(s: RuntimeSettings) -> None:
    if s.embedding.provider not in EMBEDDING_MODELS:
        raise ValueError(f"不支持的嵌入提供方: {s.embedding.provider}")
    if s.rerank.provider not in RERANK_MODELS:
        raise ValueError(f"不支持的重排提供方: {s.rerank.provider}")
    llm_ids = {p["id"] for p in LLM_PROVIDERS}
    if s.llm.provider not in llm_ids:
        raise ValueError(f"不支持的 LLM 提供方: {s.llm.provider}")


# ─── 索引联动 ────────────────────────────────────────────────────


def _embedding_sig(emb: EmbeddingSettings) -> str:
    """嵌入配置指纹:provider/model/base_url/key 任一变化 → 指纹变 → 需重建。"""
    raw = f"{emb.provider}|{emb.model}|{emb.base_url}|{emb.api_key}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _seed_index_sig(s: RuntimeSettings) -> None:
    """首次启动且已有索引时,把「构建索引用的嵌入配置」记为当前值。

    场景:克隆项目 → 用 .env 的嵌入配置建库 → 没生成过 settings.json。
    此时 index.embedding_sig 为空,但索引确实是用当前配置建的,应视作「无需重建」。
    """
    if not s.index.embedding_sig and config.MANIFEST_PATH.exists():
        s.index.embedding_sig = _embedding_sig(s.embedding)


def needs_reindex() -> bool:
    """嵌入配置变更且知识库非空 → 必须重建索引后才能正常检索。"""
    s = load_settings()
    if not config.MANIFEST_PATH.exists():
        return False
    return s.index.embedding_sig != _embedding_sig(s.embedding)


def effective_rerank_api_key() -> str:
    """重排 key 缺省复用嵌入 key(与 .env 时代共用 DASHSCOPE_API_KEY 一致)。"""
    s = load_settings()
    return s.rerank.api_key or s.embedding.api_key


# ─── 密钥掩码 ────────────────────────────────────────────────────


def mask_key(key: str) -> str:
    """sk-8276...b0 → sk-8276****b0;空 key 返回空串。"""
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}****{key[-4:]}"


def to_public(s: RuntimeSettings | None = None) -> dict:
    """把生效设置转成可安全返回给前端的字典:key 全部掩码,附选项与索引状态。"""
    s = s or load_settings()
    llm_key = s.llm.api_key
    emb_key = s.embedding.api_key
    rerank_key = effective_rerank_api_key()
    return {
        "llm": {
            **s.llm.model_dump(exclude={"api_key"}),
            "api_key": mask_key(llm_key),
            "has_key": bool(llm_key),
        },
        "embedding": {
            **s.embedding.model_dump(exclude={"api_key"}),
            "api_key": mask_key(emb_key),
            "has_key": bool(emb_key),
        },
        "rerank": {
            **s.rerank.model_dump(exclude={"api_key"}),
            "api_key": mask_key(rerank_key),
            "has_key": bool(rerank_key),
        },
        "options": {
            "llm_providers": LLM_PROVIDERS,
            "embedding_models": EMBEDDING_MODELS,
            "rerank_models": RERANK_MODELS,
        },
        "needs_reindex": needs_reindex(),
        "rebuilding": s.index.rebuilding,
        "progress": s.index.progress,
        "last_rebuilt_at": s.index.last_rebuilt_at,
        "last_rebuild_error": s.index.last_rebuild_error,
    }


# ─── 索引重建状态(供重建线程上报进度)─────────────────────────

def begin_rebuild() -> None:
    """标记重建开始(幂等:已在重建中则抛错,防重复触发)。"""
    s = load_settings()
    if s.index.rebuilding:
        raise RuntimeError("索引重建已在进行中")
    s.index.rebuilding = True
    s.index.progress = 0
    s.index.last_rebuild_error = ""
    save_settings(s)


def report_rebuild_progress(done: int, total: int) -> None:
    """重建线程每编码完一批 chunk 回调一次,更新 0-100 进度。"""
    s = load_settings()
    s.index.progress = round(done / total * 100)
    save_settings(s)


def finish_rebuild(error: str = "") -> None:
    """重建结束:成功则记录「当前索引用的嵌入配置」指纹,失败则记错误。"""
    s = load_settings()
    s.index.rebuilding = False
    if error:
        s.index.last_rebuild_error = error
    else:
        s.index.embedding_sig = _embedding_sig(s.embedding)
        s.index.progress = 100
        s.index.last_rebuilt_at = datetime.now().isoformat(timespec="seconds")
    save_settings(s)


# ─── 单例失效(模型配置变更后调用)───────────────────────────────

def invalidate_singletons() -> None:
    """清掉所有已构造的模型单例,下次调用按新配置重建。

    函数内 import 避免循环依赖:embeddings/llm/reranker 都 import 本模块。
    """
    from backend.services.embeddings import invalidate_embedding
    from backend.services.llm import invalidate_llm
    from backend.services.reranker import invalidate_reranker

    invalidate_embedding()
    invalidate_llm()
    invalidate_reranker()
