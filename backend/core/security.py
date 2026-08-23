"""密码哈希(scrypt,标准库)+ JWT 令牌(pyjwt,HS256)。

选型理由:
- scrypt 是内存困难型 KDF(比纯哈希更抗 GPU 暴力),Python hashlib 内置,
  不需要 bcrypt 这种重依赖。
- JWT 用业界标准的 pyjwt 而非手写签名,避免「自己造轮子出漏洞」。
"""

import base64
import hashlib
import hmac
import os
import time

import jwt

from backend.core.secret import get_secret_key

# scrypt 参数:n 越大越慢、越抗暴力;默认值对单机登录足够
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1


def hash_password(password: str) -> str:
    """scrypt 加盐哈希,格式 scrypt$n$r$salt_b64$digest_b64(自描述,便于调参)。"""
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32
    )
    return "$".join(
        ["scrypt", str(_SCRYPT_N), str(_SCRYPT_R),
         base64.b64encode(salt).decode(), base64.b64encode(digest).decode()]
    )


def verify_password(password: str, stored: str) -> bool:
    """校验密码;存储格式损坏或参数异常一律返回 False(不泄露细节)。"""
    try:
        _, n, r, salt_b64, digest_b64 = stored.split("$")
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=_SCRYPT_P, dklen=len(expected)
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


TOKEN_TTL_SECONDS = 7 * 24 * 3600  # 登录态默认 7 天


def create_token(user: dict, expires_seconds: int = TOKEN_TTL_SECONDS) -> str:
    """签发 JWT,payload 只放最小身份信息(不放大对象/敏感字段)。"""
    now = int(time.time())
    payload = {
        "sub": str(user["id"]),
        "username": user["username"],
        "role": user["role"],
        "iat": now,
        "exp": now + expires_seconds,
    }
    return jwt.encode(payload, get_secret_key(), algorithm="HS256")


def decode_token(token: str) -> dict | None:
    """解析 JWT;过期/篡改返回 None(调用方转 401)。"""
    try:
        return jwt.decode(token, get_secret_key(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
