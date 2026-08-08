"""中文感知的文本切分。

RecursiveCharacterTextSplitter 按分隔符优先级递归切块:对中文,把「句读」
(。！？；，)放在换行之后、空格之前,尽量保证块边界落在语义完整的句子处,
而不是把一句话拦腰切断。chunk 间留 overlap,避免切在关键信息中间。
"""

from langchain_text_splitters import RecursiveCharacterTextSplitter

from backend.core import config


def get_splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
        separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
    )


def split_documents(docs) -> list:
    """把加载后的 Document 列表切块。每个 chunk 继承原 Document 的 metadata。"""
    return get_splitter().split_documents(docs)
