"""单文档接入管线:load → split → 打元数据(doc_id / chunk_index)。

注意:本模块只产出「带好 id 的 chunk 列表」,不直接写 Chroma。
Chroma 写入与 manifest 维护由 IndexManager 负责,保证所有索引变更
收敛到一个入口。
"""

from pathlib import Path

from langchain_core.documents import Document

from backend.ingestion.chunker import split_documents
from backend.ingestion.loaders import load_document


def ingest_document(file_path: str | Path, doc_id: str) -> list[Document]:
    """加载单个文档并切块,给每个 chunk 打上 doc_id 与 chunk_index。

    Args:
        file_path: 文档路径
        doc_id: 文档内容寻址 id(由 IndexManager 计算)

    Returns:
        带完整 metadata 的 chunk 列表;每个 chunk 的 metadata 至少含
        doc_id / chunk_index / source / fmt。
    """
    file_path = Path(file_path)
    docs = load_document(file_path)

    # 先按「原始页/原始文本块」切分,再统一打 chunk_index
    chunks = split_documents(docs)
    for i, chunk in enumerate(chunks):
        chunk.metadata.update(
            {
                "doc_id": doc_id,
                "chunk_index": i,
                "source": file_path.name,
                "fmt": file_path.suffix.lstrip(".").lower(),
            }
        )
    return chunks
