"""FastAPI 入口:挂载业务路由 + 前端静态页。

启动:start.bat(固定 127.0.0.1:8001)或手动
    uvicorn backend.main:app --reload
  - 前端:  http://127.0.0.1:8001/
  - API 文档: http://127.0.0.1:8001/docs
  - 健康检查: http://127.0.0.1:8001/healthz
"""

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.api.auth import router as auth_router
from backend.api.routes import chat, documents, health, sessions, settings
from backend.core import config

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动初始化:建 SQLite 库;缺 LLM key 只警告不拦截(检索类功能仍可用)。"""
    from backend.db import repositories
    from backend.db.database import init_db
    from backend.core import settings as core_settings

    init_db()
    # CLI 建库的文档没有 DB 元数据 → 补为「语料库文档」(全员可见),
    # 保证权限过滤不会把历史文档屏蔽掉(见 repositories.sync_documents_from_manifest)
    if config.MANIFEST_PATH.exists():
        repositories.sync_documents_from_manifest(
            json.loads(config.MANIFEST_PATH.read_text(encoding="utf-8"))
        )
    s = core_settings.load_settings()
    if not s.llm.api_key:
        logger.warning("⚠️ 未配置 LLM API Key,聊天功能不可用(检索/文档管理/登录仍可用)")
    yield


app = FastAPI(
    title="企业知识助手 RAG",
    description="多格式接入 · 混合检索与重排 · 带引用多轮对话 · 增量文档管理 · 登录鉴权 · 评估体系",
    version="1.1.0",
    lifespan=lifespan,
)

# 健康检查在根路径(不加 /api 前缀,Docker/K8s 探针约定)
app.include_router(health.router)
app.include_router(auth_router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")
app.include_router(settings.router, prefix="/api")

# 前端静态页(单页 HTML,无构建工具)
_static_dir = config.PROJECT_ROOT / "frontend" / "static"
if _static_dir.exists():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="frontend")
