"""POST /api/chat —— 多轮带引用问答。"""

from fastapi import APIRouter, HTTPException

from backend.api.schemas import ChatRequest, ChatResponse, SourceInfo
from backend.services.rag_service import get_service

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    try:
        result = get_service().answer(req.session_id, req.question)
    except Exception as e:  # noqa: BLE001 —— 统一转 500,避免堆栈泄漏给前端
        raise HTTPException(status_code=500, detail=f"服务异常: {e}") from e

    return ChatResponse(
        answer=result["answer"],
        sources=[SourceInfo(**s) for s in result["sources"]],
        session_id=req.session_id,
    )
