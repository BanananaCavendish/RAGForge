"""聊天 API:非流式 POST /api/chat + 流式 POST /api/chat/stream(SSE)。

权限:需登录;检索结果按当前用户可访问的文档过滤(ACL)。
成本控制:每用户每分钟请求数上限(429)。
"""

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from backend.api.deps import get_current_user
from backend.api.schemas import ChatRequest, ChatResponse, SourceInfo
from backend.core import settings
from backend.db import repositories
from backend.services.rag_service import RAGService, get_service
from backend.services.rate_limit import chat_limiter

router = APIRouter(tags=["chat"])


def _resolve_session(req: ChatRequest, user: dict) -> str:
    """返回「属于当前用户」的会话 id;未传或不存在的会话则自动新建。

    归属校验:别人的会话绝不复用(改了会写进别人的历史里),前端总是
    用服务端创建的会话 id 提问。
    """
    if req.session_id:
        if repositories.get_session(req.session_id, user["id"]):
            return req.session_id
        if repositories.session_exists(req.session_id):
            raise HTTPException(status_code=403, detail="无权访问该会话")
    return repositories.create_session(user["id"], title="新会话")


@router.post("/chat", response_model=ChatResponse)
def chat(
    req: ChatRequest,
    user: dict = Depends(get_current_user),
    service: RAGService = Depends(get_service),
) -> ChatResponse:
    chat_limiter.check(user["id"])
    if settings.needs_reindex():
        raise HTTPException(
            status_code=409,
            detail="嵌入模型已变更,请先在「设置」页重建索引后再提问。",
        )

    session_id = _resolve_session(req, user)
    allowed = repositories.allowed_doc_ids(user)
    try:
        result = service.answer(
            session_id, req.question, user_id=user["id"], allowed_doc_ids=allowed
        )
    except Exception as e:  # noqa: BLE001 —— 统一转 500,避免堆栈泄漏给前端
        raise HTTPException(status_code=500, detail=f"服务异常: {e}") from e

    return ChatResponse(
        answer=result["answer"],
        sources=[SourceInfo(**s) for s in result["sources"]],
        session_id=session_id,
    )


@router.post("/chat/stream")
def chat_stream(
    req: ChatRequest,
    user: dict = Depends(get_current_user),
    service: RAGService = Depends(get_service),
) -> StreamingResponse:
    chat_limiter.check(user["id"])
    if settings.needs_reindex():
        raise HTTPException(
            status_code=409,
            detail="嵌入模型已变更,请先在「设置」页重建索引后再提问。",
        )

    session_id = _resolve_session(req, user)
    allowed = repositories.allowed_doc_ids(user)

    def gen():
        try:
            for ev in service.answer_stream(
                session_id, req.question, user_id=user["id"], allowed_doc_ids=allowed
            ):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as e:  # noqa: BLE001 —— 流式中途故障转 SSE 错误事件
            yield f"data: {json.dumps({'type': 'error', 'message': f'服务异常: {e}'}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
