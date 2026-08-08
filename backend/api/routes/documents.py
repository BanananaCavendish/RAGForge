"""文档管理 API:增 / 删 / 列 / 替换 —— 演示「增量更新」不用全量重建。

上传文件保存到临时目录(增量索引),由 IndexManager 做内容寻址幂等。
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile

from backend.api.schemas import DocAddResponse, DocInfo, DocListResponse
from backend.core import config
from backend.services.rag_service import get_manager

router = APIRouter(tags=["documents"])

# 支持接入的格式
ALLOWED_SUFFIXES = {".pdf", ".docx", ".html", ".htm", ".md", ".txt"}

UPLOAD_DIR = config.DATA_DIR / "uploads"


def _save_upload(file: UploadFile) -> Path:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail=f"不支持的文件格式: {suffix}")
    path = UPLOAD_DIR / file.filename
    with path.open("wb") as f:
        f.write(file.file.read())
    return path


@router.get("/documents", response_model=DocListResponse)
def list_documents() -> DocListResponse:
    docs = get_manager().list_documents()
    return DocListResponse(documents=[DocInfo(**d) for d in docs])


@router.post("/documents", response_model=DocAddResponse, status_code=201)
def add_document(file: UploadFile) -> DocAddResponse:
    path = _save_upload(file)
    manager = get_manager()
    doc_id = manager.add_document(path)
    info = manager.get_document(doc_id)
    return DocAddResponse(**{"doc_id": doc_id, **info})


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: str) -> dict:
    ok = get_manager().delete_document(doc_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"未找到文档: {doc_id}")
    return {"doc_id": doc_id, "deleted": True}


@router.put("/documents/{doc_id}", response_model=DocAddResponse)
def replace_document(doc_id: str, file: UploadFile) -> DocAddResponse:
    path = _save_upload(file)
    manager = get_manager()
    new_doc_id = manager.replace_document(doc_id, path)
    info = manager.get_document(new_doc_id)
    return DocAddResponse(**{"doc_id": new_doc_id, **info})
