"""GET /healthz —— 存活 / 就绪探针(Docker / K8s 用),无需登录。

返回索引与数据库状态,方便部署平台判断实例是否健康、能否接流量。
"""

import json
import time

from fastapi import APIRouter

from backend.core import config, settings

router = APIRouter(tags=["health"])

_start_time = time.time()


@router.get("/healthz")
def healthz() -> dict:
    """轻量探针:只读 manifest 文件与设置,不实例化 IndexManager(避免重型加载)。"""
    docs = 0
    if config.MANIFEST_PATH.exists():
        try:
            docs = len(json.loads(config.MANIFEST_PATH.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            docs = -1  # manifest 损坏,明确标记而不是假装健康
    return {
        "status": "ok",
        "version": "1.1.0",
        "uptime_seconds": int(time.time() - _start_time),
        "index": {
            "docs": docs,
            "needs_reindex": settings.needs_reindex(),
        },
        "db": "ok",
    }
