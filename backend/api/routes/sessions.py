"""会话管理 API:创建 / 列表 / 消息 / 删除 —— 会话持久化的对外出口。

前端流程:登录后建一个会话 → 用返回的 id 提问 → 切换/删除会话。
"""

from fastapi import APIRouter, Depends, HTTPException

from backend.api.deps import get_current_user
from backend.api.schemas import (
    MessageInfo,
    SessionCreateResponse,
    SessionInfo,
    SessionMessagesResponse,
)
from backend.db import repositories
from backend.services import session_store

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionCreateResponse)
def create_session(user: dict = Depends(get_current_user)) -> SessionCreateResponse:
    sid = session_store.store.create_session(user["id"])
    return SessionCreateResponse(id=sid, title="新会话")


@router.get("", response_model=list[SessionInfo])
def list_sessions(user: dict = Depends(get_current_user)) -> list[SessionInfo]:
    return [SessionInfo(**s) for s in session_store.store.list_sessions(user["id"])]


@router.get("/{session_id}/messages", response_model=SessionMessagesResponse)
def session_messages(session_id: str, user: dict = Depends(get_current_user)) -> SessionMessagesResponse:
    if not repositories.get_session(session_id, user["id"]):
        raise HTTPException(status_code=404, detail="会话不存在")
    return SessionMessagesResponse(
        messages=[MessageInfo(**m) for m in repositories.list_messages(session_id)]
    )


@router.delete("/{session_id}")
def delete_session(session_id: str, user: dict = Depends(get_current_user)) -> dict:
    if not session_store.store.delete_session(session_id, user["id"]):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"deleted": True}
