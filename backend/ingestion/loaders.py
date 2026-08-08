"""多格式文档加载器:按扩展名分派。

支持:.pdf / .docx / .html / .md / .txt
依赖选择刻意轻量:
  - .docx 用 docx2txt(PyPDF 那套的轻量替代),不用 Unstructured*(依赖重)。
  - .html 用 BeautifulSoup 抽取正文。
"""

from pathlib import Path

from langchain_community.document_loaders import (
    BSHTMLLoader,
    Docx2txtLoader,
    PyPDFLoader,
    TextLoader,
)
from langchain_core.documents import Document

LOADER_BY_EXT = {
    ".pdf": PyPDFLoader,
    ".docx": Docx2txtLoader,
    ".html": BSHTMLLoader,
    ".htm": BSHTMLLoader,
    ".md": TextLoader,
    ".txt": TextLoader,
}


def get_loader(path: str | Path):
    ext = Path(path).suffix.lower()
    loader_cls = LOADER_BY_EXT.get(ext)
    if loader_cls is None:
        raise ValueError(f"不支持的文档格式: {ext}(支持: {', '.join(LOADER_BY_EXT)})")
    kwargs: dict = {}
    if loader_cls is TextLoader:
        kwargs = {"encoding": "utf-8"}
    if loader_cls is BSHTMLLoader:
        # Windows 默认编码是 GBK,必须显式指定 UTF-8 读取 HTML
        kwargs = {"open_encoding": "utf-8"}
    return loader_cls(str(path), **kwargs)


def load_document(path: str | Path) -> list[Document]:
    """加载单个文档,返回 Document 列表(PDF 可能多页)。

    返回的 Document 带基础 metadata(source=文件名, fmt=格式),
    由调用方(ingest)再补 doc_id / chunk_index。
    """
    path = Path(path)
    docs = get_loader(path).load()
    for doc in docs:
        # 强制覆盖 source 为「纯文件名」:部分 loader(PyPDFLoader 等)会把
        # 绝对路径塞进 metadata,统一为文件名便于 golden 评估与前端展示。
        doc.metadata["source"] = path.name
        doc.metadata["fmt"] = path.suffix.lstrip(".").lower()
    return docs
