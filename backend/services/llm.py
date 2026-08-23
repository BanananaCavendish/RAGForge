"""LLM 工厂:统一创建 ChatOpenAI(DeepSeek / 任意 OpenAI 兼容端点)。

为什么不用 langchain_community 的 ChatDeepSeek?——DeepSeek 提供标准 OpenAI
兼容端点,用 ChatOpenAI 接入代码更简单,也方便日后换任意兼容模型。

配置来源:运行时设置(settings.json 覆盖 .env),前端「设置」页可改。
"""

from langchain_openai import ChatOpenAI

from backend.core import settings

_singleton: ChatOpenAI | None = None


def _build_llm(temperature: float) -> ChatOpenAI:
    """按运行时设置构造 ChatOpenAI;key 缺失时抛带指引的 ValueError。"""
    s = settings.load_settings().llm
    if not s.api_key:
        raise ValueError(
            "\n❌ 缺少 LLM API Key\n"
            "   请在网页「设置」页填入,或写入 .env 的 DEEPSEEK_API_KEY\n"
        )
    return ChatOpenAI(
        model=s.model,
        base_url=s.base_url,
        api_key=s.api_key,
        temperature=temperature,
    )


def get_llm() -> ChatOpenAI:
    """对话用 LLM(带一定温度,适度多样)。模块级单例,避免重复构造。"""
    global _singleton
    if _singleton is None:
        _singleton = _build_llm(settings.load_settings().llm.temperature)
    return _singleton


def get_judge_llm() -> ChatOpenAI:
    """评估用 LLM:temperature=0,确定性判断,不缓存(避免与对话 LLM 共用计数)。"""
    return _build_llm(0.0)


def invalidate_llm() -> None:
    """配置变更后清掉单例,下次 get_llm() 按新配置重建。"""
    global _singleton
    _singleton = None
