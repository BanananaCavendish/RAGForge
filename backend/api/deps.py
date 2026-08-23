"""FastAPI 安全依赖:从 Bearer Token 解析当前用户 / 管理员。

用法:
  def foo(user: dict = Depends(get_current_user)): ...       # 需登录
  def bar(user: dict = Depends(get_admin_user)): ...         # 需管理员
"""

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.core.security import decode_token
from backend.db import repositories

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """校验请求头 Authorization: Bearer <token>,返回当前用户行。"""
    if credentials is None:
        raise HTTPException(status_code=401, detail="未登录,请先登录")
    payload = decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="登录已过期,请重新登录")
    user = repositories.get_user_by_id(int(payload["sub"]))
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    return user


def get_admin_user(user: dict = Depends(get_current_user)) -> dict:
    """在 get_current_user 基础上要求管理员角色(设置页/文档管理)。"""
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="该操作需要管理员权限")
    return user
