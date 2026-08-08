"""LLM-as-judge:忠实度(整体)与引用准确率(局部)的判定。

为什么用 LLM 判:忠实度 / 引用支撑 都是「开放性」判断,规则难以穷举,
LLM 是唯一可规模化判定的方式。
为什么可控:
  - temperature=0,保证可复现;
  - 结构化输出(with_structured_output),结果必然可解析;
  - 每个判定带 reason 字段,可人工抽检;
  - 口径明确:忠实度判「整段答案是否完全被上下文支持」,
          引用准确率判「每条 [i] 是否真支撑它紧邻的那句陈述」。
局限(面试要主动讲):judge 可能偏宽松/存在位置偏差 → 用金标抽样人工复核。
"""

import json
import logging
import re
from typing import TypeVar

from pydantic import BaseModel, Field

from backend.services.llm import get_judge_llm

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


# =====================================================================
# Prompts
# =====================================================================

FAITHFUL_PROMPT = """你是严格的事实核查员。判断下面的「回答」是否完全由「参考上下文」支持。
规则:
- 回答中每条关键信息(数字、事实、结论)都必须能在参考上下文里找到依据,不得编造或过度推断。
- 回答中的 [1][2] 等序号标注指向参考上下文的第 1、2 段,可用于核对。
- 只要存在一条与上下文矛盾、或上下文完全未提及的断言,就判定为不忠实(faithful=false)。

参考上下文:
{context}

回答:
{answer}

只输出 JSON:{{"faithful": true 或 false, "reason": "一句话理由"}}"""

CITATION_PROMPT = """你是事实核查员。核对「回答」中的引用标注。
回答里的 [1]、[2] 等标记指向「参考上下文」的第 1、2 段。
对回答中出现的每一个引用,判断:该片段是否真的支撑了紧邻该引用编号的那句陈述。
只要该片段没有支撑紧邻的陈述(supported=false),即使整段回答没错也一样 false。

参考上下文:
{context}

回答:
{answer}

只输出 JSON:{{"citations": [{{"idx": 1, "supported": true, "reason": "一句话理由"}}]}}"""


# =====================================================================
# 结构化输出模型
# =====================================================================

class FaithfulnessVerdict(BaseModel):
    faithful: bool
    reason: str = Field(description="一句话说明判断理由")


class CitationItem(BaseModel):
    idx: int
    supported: bool
    reason: str = ""


class CitationVerdict(BaseModel):
    citations: list[CitationItem]


# =====================================================================
# 执行(带 JSON 兜底)
# =====================================================================


def _structured_or_json(model_cls: type[T], prompt: str) -> T:
    """优先 with_structured_output;失败时从文本里抽 JSON 兜底。"""
    llm = get_judge_llm()
    try:
        chain = llm.with_structured_output(model_cls)
        return chain.invoke(prompt)
    except Exception as e:  # noqa: BLE001
        logger.warning("structured output 失败(%s),走 JSON 兜底", e)
        text = llm.invoke(prompt).content
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            raise ValueError(f"无法从 judge 输出解析 JSON: {text[:200]}") from e
        return model_cls.model_validate_json(m.group(0))


def judge_faithful(context: str, answer: str) -> FaithfulnessVerdict:
    """判整段答案是否完全被参考上下文支持。"""
    if not answer.strip():
        return FaithfulnessVerdict(faithful=False, reason="空答案")
    return _structured_or_json(
        FaithfulnessVerdict, FAITHFUL_PROMPT.format(context=context, answer=answer)
    )


def judge_citations(context: str, answer: str) -> CitationVerdict:
    """判每条引用是否被支撑。返回空列表 = 回答里没有引用标注。"""
    if not re.search(r"\[\d+\]", answer):
        return CitationVerdict(citations=[])
    return _structured_or_json(
        CitationVerdict, CITATION_PROMPT.format(context=context, answer=answer)
    )
