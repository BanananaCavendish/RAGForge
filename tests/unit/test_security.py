"""密码哈希(scrypt)与 JWT 令牌单元测试。"""


def test_password_hash_verify_roundtrip():
    from backend.core.security import hash_password, verify_password

    h = hash_password("secret123")
    assert h.startswith("scrypt$")
    assert verify_password("secret123", h)
    assert not verify_password("wrong-password", h)


def test_password_hash_is_salted():
    from backend.core.security import hash_password

    # 同密码两次哈希不同(随机盐),防止彩虹表
    assert hash_password("secret123") != hash_password("secret123")


def test_jwt_roundtrip():
    from backend.core.security import create_token, decode_token

    token = create_token({"id": 7, "username": "alice", "role": "admin"})
    payload = decode_token(token)
    assert payload is not None
    assert payload["sub"] == "7"
    assert payload["username"] == "alice"
    assert payload["role"] == "admin"


def test_jwt_tampered_rejected():
    from backend.core.security import create_token, decode_token

    token = create_token({"id": 1, "username": "u", "role": "user"})
    tampered = token[:-4] + "AAAA"
    assert decode_token(tampered) is None
