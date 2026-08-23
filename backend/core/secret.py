"""服务器端机密:JWT 签名 + settings.json API Key 加密共用一把钥匙。

来源优先级:
  1. 环境变量 SECRET_KEY —— 生产环境显式注入(便于在部署平台管理/轮换)
  2. data/.secret —— 首次启动自动生成并落盘(.gitignore 忽略)

注意:一旦换密钥,已签发的 JWT 全部失效、已加密的 API Key 解不开(需重填)。
这就是把密钥放环境变量的原因——部署层面该告警告警、该轮换轮换。
"""

import base64
import os

from backend.core import config


def get_secret_key() -> str:
    """返回 urlsafe-base64 的 32 字节随机密钥(字符串形式)。"""
    env = os.environ.get("SECRET_KEY")
    if env:
        return env.strip()

    path = config.DATA_DIR / ".secret"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()

    path.parent.mkdir(parents=True, exist_ok=True)
    key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    path.write_text(key, encoding="utf-8")
    return key
