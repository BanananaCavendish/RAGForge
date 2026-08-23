"""文档管理 API:上传(异步后台摄取 + 进度)/ 删除 / 列表 / 替换。

权限模型(多用户):
- 上传:任意登录用户;上传者成为 owner(记录 uploaded_by)。
- 列表:admin 见全部;普通用户见「语料库文档 + 自己上传的 + 分享给自己的」。
- 删除/替换:admin 或 owner 本人;无权返回 403。
- 设置 / 重建索引:admin 专属(见 settings.py)。

异步摄取(Tier1):
  POST /documents → 立即返回 202 + task_id,pending 状态
  后台线程:解析 → 嵌入 → 入库 → 写元数据/ACL → 任务 done
  前端轮询 GET /documents/tasks 看进度;失败时 error 里带原因。
"""

import json
import threading
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from backend.api.deps import get_current_user
from backend.api.schemas import DocAddResponse, DocInfo, DocListResponse, TaskInfo, TaskListResponse, UploadResponse
from backend.core import config, settings
from backend.db import repositories
from backend.services.index_manager import IndexManager
from backend.services.rag_service import get_manager

router = APIRouter(tags=["documents"])

# 支持接入的格式
ALLOWED_SUFFIXES = {".pdf", ".docx", ".html", ".htm", ".md", ".txt"}


def _upload_dir() -> Path:
    """上传临时目录。惰性计算:config.DATA_DIR 可能被测试重定向。"""
    d = config.DATA_DIR / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_display_name(raw: str) -> str:
    """取原始文件名的 basename,剥离一切路径分隔符(兼容 Windows `\\` 与 POSIX `/`)。

    安全意义:上传文件名是用户可控输入,若直接拼进路径可被 `../../` 或盘符
    绕过目录边界(路径遍历漏洞)。这里只保留最后的文件名片段。
    """
    base = raw.replace("\\", "/").split("/")[-1].strip()
    return base or "unnamed"


def _save_upload(file: UploadFile) -> tuple[Path, str]:
    """保存上传文件到临时目录,返回 (磁盘路径, 展示用原始文件名)。"""
    display_name = _safe_display_name(file.filename or "")
    suffix = Path(display_name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail=f"不支持的文件格式: {suffix}")
    path = _upload_dir() / f"{uuid4().hex}{suffix}"
    with path.open("wb") as f:
        f.write(file.file.read())
    return path, display_name


def _run_ingestion(
    task_id: int, path: Path, display_name: str, user_id: int, manager: IndexManager
) -> None:
    """后台摄取线程:解析→嵌入→入库→登记元数据/ACL→更新任务状态。

    成功后 invalidate_services():让下次对话按新索引重建检索链
    (BM25/corpus 是构造时快照,增量加文档后必须刷新)。
    """
    from backend.services.rag_service import invalidate_services

    try:
        repositories.update_task(task_id, status="running", progress=0)
        doc_id = manager.add_document(path, source_name=display_name)
        info = manager.get_document(doc_id)
        repositories.upsert_document(doc_id, display_name, info["fmt"], info["num_chunks"], user_id)
        repositories.add_acl(doc_id, user_id)  # owner 显式进 ACL,表里留痕
        repositories.update_task(task_id, status="done", progress=100, doc_id=doc_id)
        invalidate_services()
    except Exception as e:  # noqa: BLE001 —— 失败如实记录到任务,前端可见
        repositories.update_task(task_id, status="failed", error=f"{type(e).__name__}: {e}")
    finally:
        path.unlink(missing_ok=True)  # 摄取完成后清理临时文件


@router.get("/documents", response_model=DocListResponse)
def list_documents(
    user: dict = Depends(get_current_user), manager: IndexManager = Depends(get_manager)
) -> DocListResponse:
    allowed = repositories.allowed_doc_ids(user)
    docs = manager.list_documents()
    if allowed is not None:
        docs = [d for d in docs if d["doc_id"] in allowed]
    # 补上传者信息:前端按「语料库 / 某用户上传」分组展示
    for d in docs:
        meta = repositories.get_document_meta(d["doc_id"])
        if meta and meta["uploaded_by"]:
            u = repositories.get_user_by_id(meta["uploaded_by"])
            d["uploaded_by"] = meta["uploaded_by"]
            d["owner"] = u["username"] if u else None
    return DocListResponse(documents=[DocInfo(**d) for d in docs])


@router.get("/documents/{doc_id}/preview")
def preview_document(
    doc_id: str,
    user: dict = Depends(get_current_user),
    manager: IndexManager = Depends(get_manager),
) -> dict:
    """文档预览:返回该文档前几个 chunk 的原文(数据源 data/texts/,不读原始文件)。"""
    allowed = repositories.allowed_doc_ids(user)
    if allowed is not None and doc_id not in allowed:
        raise HTTPException(status_code=403, detail="无权查看该文档")
    info = manager.get_document(doc_id)
    if not info:
        raise HTTPException(status_code=404, detail="文档不存在")
    path = manager._text_path(doc_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="文档文本缺失(可能未完成摄取)")
    chunks = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()[:5]):
        chunks.append({"index": i, "text": json.loads(line)["page_content"]})
    return {"doc_id": doc_id, "filename": info["filename"], "chunks": chunks}


@router.post("/documents", response_model=UploadResponse, status_code=202)
def add_document(
    file: UploadFile,
    user: dict = Depends(get_current_user),
    manager: IndexManager = Depends(get_manager),
) -> UploadResponse:
    if settings.needs_reindex():
        raise HTTPException(
            status_code=409,
            detail="嵌入模型已变更,请先在「设置」页重建索引后再上传文档。",
        )
    path, display_name = _save_upload(file)
    task_id = repositories.create_task(display_name, created_by=user["id"])
    threading.Thread(
        target=_run_ingestion,
        args=(task_id, path, display_name, user["id"], manager),
        daemon=True,
    ).start()
    return UploadResponse(task_id=task_id, status="pending")


@router.get("/documents/tasks", response_model=TaskListResponse)
def list_tasks(user: dict = Depends(get_current_user)) -> TaskListResponse:
    tasks = repositories.list_tasks(limit=20)
    if user["role"] != "admin":
        tasks = [t for t in tasks if t["created_by"] == user["id"]]
    return TaskListResponse(tasks=[TaskInfo(**t) for t in tasks])


def _check_doc_permission(doc_id: str, user: dict) -> None:
    """删除/替换前校验:admin 或 owner 才可操作。"""
    meta = repositories.get_document_meta(doc_id)
    if meta and user["role"] != "admin" and meta["uploaded_by"] != user["id"]:
        raise HTTPException(status_code=403, detail="无权操作该文档(仅管理员或上传者可删)")


@router.delete("/documents/{doc_id}")
def delete_document(
    doc_id: str,
    user: dict = Depends(get_current_user),
    manager: IndexManager = Depends(get_manager),
) -> dict:
    _check_doc_permission(doc_id, user)
    ok = manager.delete_document(doc_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"未找到文档: {doc_id}")
    repositories.delete_document_meta(doc_id)  # ACL 随文档级联删除
    return {"doc_id": doc_id, "deleted": True}


@router.put("/documents/{doc_id}", response_model=DocAddResponse)
def replace_document(
    doc_id: str,
    file: UploadFile,
    user: dict = Depends(get_current_user),
    manager: IndexManager = Depends(get_manager),
) -> DocAddResponse:
    _check_doc_permission(doc_id, user)
    path, display_name = _save_upload(file)
    try:
        new_doc_id = manager.replace_document(doc_id, path)
        info = manager.get_document(new_doc_id)
        repositories.delete_document_meta(doc_id)
        repositories.upsert_document(new_doc_id, display_name, info["fmt"], info["num_chunks"], user["id"])
        return DocAddResponse(**{"doc_id": new_doc_id, **info})
    finally:
        path.unlink(missing_ok=True)
