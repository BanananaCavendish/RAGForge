"""LLM 工厂:统一创建 ChatOpenAI(DeepSeek,OpenAI 兼容接口)。

为什么不用 langchain_community 的 ChatDeepSeek?——DeepSeek 提供标准 OpenAI
兼容端点,用 ChatOpenAI 接入代码更简单,也方便日后换任意兼容模型。
"""

from langchain_openai import ChatOpenAI

from backend.core import config

_singleton: ChatOpenAI | None = None


def get_llm() -> ChatOpenAI:
    """对话用 LLM(带一定温度,适度多样)。模块级单例,避免重复构造。"""
    global _singleton
    if _singleton is None:
        config.validate_config()
        _singleton = ChatOpenAI(
            model=config.LLM_MODEL,
            base_url=config.DEEPSEEK_BASE_URL,
            api_key=config.DEEPSEEK_API_KEY,
            temperature=config.LLM_TEMPERATURE,
        )
    return _singleton


def get_judge_llm() -> ChatOpenAI:
    """评估用 LLM:temperature=0,确定性判断,不缓存(避免与对话 LLM 共用计数)。"""
    config.validate_config()
    return ChatOpenAI(
        model=config.LLM_MODEL,
        base_url=config.DEEPSEEK_BASE_URL,
        api_key=config.DEEPSEEK_API_KEY,
        temperature=0.0,
    )
