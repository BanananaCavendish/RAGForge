"""模型设置 API:客户在网页上配置 LLM / 嵌入 / 重排模型与 API Key。

权限:全部接口仅管理员可访问(模型/密钥属全局敏感配置,普通用户不碰)。

安全约定:
- GET 只返回掩码后的 key(sk-****abcd)+ 是否已配置,绝不全量回传。
- PUT 接收明文 key;落盘前用 Fernet 加密(密钥来自 data/.secret / SECRET_KEY)。
- 本地/内网明文传输可接受;公网部署应置于 HTTPS 之后(见 docker-compose)。

索引联动(核心):
- 切换嵌入模型 → 向量维度/语义空间变 → 旧索引作废。
- PUT 后 needs_reindex=true,前端弹「重建索引」;重建跑在后台线程,
  GET 轮询进度,完成后 next 请求自动加载新索引。
"""

import threading

from fastapi import APIRouter, Depends, HTTPException

from backend.api.deps import get_admin_user
from backend.api.schemas import ConnectionTestRequest, SettingsUpdate
from backend.core import config, settings
from backend.services import connectivity
from backend.services.index_manager import IndexManager
from backend.services.rag_service import (
    get_manager,
    invalidate_services,
)

router = APIRouter(tags=["settings"])


# ─── 读 / 写 ─────────────────────────────────────────────────────


@router.get("/settings")
def get_settings(_admin: dict = Depends(get_admin_user)) -> dict:
    """当前生效配置(掩码 key)+ 可选模型清单 + 索引状态。"""
    return settings.to_public()


@router.put("/settings")
def update_settings(req: SettingsUpdate, _admin: dict = Depends(get_admin_user)) -> dict:
    """保存配置。只更新提交的字段;api_key 不传=保留,传""=清除。"""
    current = settings.load_settings()
    if current.index.rebuilding:
        raise HTTPException(status_code=409, detail="索引正在重建中,请稍后再修改配置")

    patch: dict = {}
    if req.llm is not None:
        patch["llm"] = req.llm.model_dump(exclude_none=True)
    if req.embedding is not None:
        patch["embedding"] = req.embedding.model_dump(exclude_none=True)
    if req.rerank is not None:
        patch["rerank"] = req.rerank.model_dump(exclude_none=True)
    if not patch:
        return settings.to_public()

    try:
        settings.update_settings(patch)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # 模型/密钥已变 → 清掉已构造的单例,下次请求按新配置重建
    settings.invalidate_singletons()
    return settings.to_public()


# ─── 连接测试(保存前先验证 key / endpoint / model)─────────────


@router.post("/settings/test")
def test_connection(req: ConnectionTestRequest, _admin: dict = Depends(get_admin_user)) -> dict:
    """按提交的候选配置测试连通性(不保存);留空字段用当前生效配置。"""
    cur = settings.load_settings()
    results: dict = {}

    # LLM:始终走 API 测试
    llm = req.llm
    llm_base = (llm.base_url if llm and llm.base_url else None) or cur.llm.base_url
    llm_key = (llm.api_key if llm and llm.api_key else None) or cur.llm.api_key
    llm_model = (llm.model if llm and llm.model else None) or cur.llm.model
    results["llm"] = connectivity.test_llm(llm_base, llm_key, llm_model)

    # 嵌入 / 重排:本地模型不测网络(离线),只测 api provider
    emb = req.embedding
    emb_provider = (emb.provider if emb and emb.provider else None) or cur.embedding.provider
    if emb_provider == "local":
        results["embedding"] = {"ok": True, "message": "本地嵌入模型,无需 API 连接测试"}
    else:
        emb_base = (emb.base_url if emb and emb.base_url else None) or cur.embedding.base_url
        emb_key = (emb.api_key if emb and emb.api_key else None) or cur.embedding.api_key
        emb_model = (emb.model if emb and emb.model else None) or cur.embedding.model
        results["embedding"] = connectivity.test_embedding(emb_base, emb_key, emb_model)

    rerank = req.rerank
    rerank_enabled = (
        rerank.enabled if rerank and rerank.enabled is not None else cur.rerank.enabled
    )
    if not rerank_enabled:
        results["rerank"] = {"ok": None, "message": "重排未启用,跳过测试"}
    else:
        rk_provider = (
            (rerank.provider if rerank and rerank.provider else None)
            or cur.rerank.provider
        )
        if rk_provider == "local":
            results["rerank"] = {"ok": True, "message": "本地重排模型,无需 API 连接测试"}
        else:
            rk = (rerank.api_key if rerank and rerank.api_key else None) or settings.effective_rerank_api_key()
            rurl = (
                (rerank.base_url if rerank and rerank.base_url else None)
                or cur.rerank.base_url
            )
            rmodel = (rerank.model if rerank and rerank.model else None) or cur.rerank.model
            results["rerank"] = connectivity.test_rerank(rurl, rk, rmodel)

    return results


# ─── 索引重建(切嵌入模型后,前端确认→手动触发)────────────────


@router.post("/settings/reindex")
def rebuild_index(
    manager: IndexManager = Depends(get_manager),
    _admin: dict = Depends(get_admin_user),
) -> dict:
    """后台线程重建全部向量。返回后前端轮询 GET /api/settings 看进度。"""
    current = settings.load_settings()
    if current.index.rebuilding:
        raise HTTPException(status_code=409, detail="索引重建已在进行中")
    if not config.MANIFEST_PATH.exists():
        raise HTTPException(status_code=400, detail="知识库为空,无需重建")

    settings.begin_rebuild()
    threading.Thread(target=_run_rebuild, args=(manager,), daemon=True).start()
    return {"started": True, "rebuilding": True}


def _run_rebuild(manager: IndexManager) -> None:
    """重建线程:用当前嵌入配置重新编码全部 chunk → 重建 FAISS+BM25 → 收尾。"""
    try:
        settings.invalidate_singletons()  # 确保 get_embedding() 用新配置构造
        manager.reindex(on_progress=settings.report_rebuild_progress)
        settings.finish_rebuild()
        invalidate_services()  # 下次请求按新索引重建 service/manager
    except Exception as e:  # noqa: BLE001 —— 失败要记到设置里,前端可见
        settings.finish_rebuild(error=f"{type(e).__name__}: {e}")
