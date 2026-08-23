"""注册 / 登录 / 当前用户 —— 登录鉴权入口。

设计:
- 首个注册的用户自动成为 admin(引导期 bootstrap),之后注册的都是普通用户。
- JWT 无状态,登出由前端丢弃 token 实现;服务端不维护黑名单(7 天过期)。
- 密码以 scrypt 哈希落库,明文绝不出现在任何日志/响应里。
"""

from fastapi import APIRouter, Depends, HTTPException

from backend.api.deps import get_current_user
from backend.api.schemas import AuthResponse, LoginRequest, RegisterRequest, UserInfo
from backend.core.security import create_token, hash_password, verify_password
from backend.db import repositories

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=AuthResponse)
def register(req: RegisterRequest) -> AuthResponse:
    username = req.username.strip()
    if len(username) < 2:
        raise HTTPException(status_code=400, detail="用户名至少 2 个字符")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="密码至少 6 位")
    if repositories.get_user_by_username(username):
        raise HTTPException(status_code=409, detail="用户名已存在")

    role = "admin" if repositories.count_users() == 0 else "user"
    user = repositories.create_user(username, hash_password(req.password), role=role)
    return AuthResponse(token=create_token(user), user=UserInfo(**user))


@router.post("/login", response_model=AuthResponse)
def login(req: LoginRequest) -> AuthResponse:
    user = repositories.get_user_by_username(req.username.strip())
    if not user or not verify_password(req.password, user["password_hash"]):
        # 统一报错文案,不泄露「用户名是否存在」
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return AuthResponse(token=create_token(user), user=UserInfo(**user))


@router.get("/me", response_model=UserInfo)
def me(user: dict = Depends(get_current_user)) -> UserInfo:
    return UserInfo(**user)
