"""中文感知切分单测:句读优先配置、内容不丢失、元数据继承。"""

from langchain_core.documents import Document

from backend.ingestion.chunker import SEPARATORS, get_splitter, split_documents


def test_separators_put_chinese_punctuation_before_spaces():
    """中文句读(。！？；，)应排在空格之前,保证句子不被拦腰切断。"""
    for punct in "。！？；，":
        assert SEPARATORS.index(punct) < SEPARATORS.index(" "), (
            f"分隔符 {punct} 应优先于空格"
        )


def test_split_produces_multiple_chunks():
    text = "内容足够长。" * 200
    parts = get_splitter().split_text(text)
    assert len(parts) >= 2


def test_split_covers_full_text():
    """切分不丢内容:原文头部落在首块、尾部落在末块。

    注意不能用 `''.join(parts) == text`:chunk_overlap 会让相邻块刻意重复
    部分内容(防止切在关键信息中间),拼接必然超过原文长度。
    """
    sentences = [f"第{i}条详细规定了公司业务的各项执行细则与配套措施。" for i in range(1, 60)]
    text = "".join(sentences)
    parts = get_splitter().split_text(text)
    assert parts[0].startswith(text[:10])
    assert parts[-1].endswith(text[-10:])


def test_split_inherits_metadata():
    """切块应继承原 Document 的 metadata(供后续打 doc_id/chunk_index)。"""
    doc = Document(page_content="第一段内容。第二段内容。", metadata={"tag": "x"})
    chunks = split_documents([doc])
    assert all(c.metadata.get("tag") == "x" for c in chunks)
