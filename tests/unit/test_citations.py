"""引用序号抽取单测。"""

from backend.services.rag_service import extract_citations


def test_extract_single():
    assert extract_citations("报销额度为 500 元[1]") == [1]


def test_extract_multiple():
    assert extract_citations("内容[1][3],以及[12]") == [1, 3, 12]


def test_extract_none():
    assert extract_citations("回答里没有引用") == []


def test_extract_ordered_by_appearance():
    assert extract_citations("先[3]后[1]") == [3, 1]
