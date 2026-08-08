"""FastAPI 入口:挂载业务路由 + 前端静态页。

启动:uvicorn backend.main:app --reload
  - 前端:  http://127.0.0.1:8000/
  - API 文档: http://127.0.0.1:8000/docs
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.api.routes import chat, documents
from backend.core import config

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时只检查 key 是否已配置,不强制失败(检索类功能无 key 也能用)。

    模型加载与索引构建是惰性的:首次请求 /chat 或 /api/documents 时触发。
    """
    if not config.DEEPSEEK_API_KEY or config.DEEPSEEK_API_KEY.startswith("sk-your-key"):
        logger.warning("⚠️ 未配置 DEEPSEEK_API_KEY,聊天功能不可用(检索/文档管理仍可用)")
    yield


app = FastAPI(
    title="企业知识助手 RAG",
    description="多格式接入 · 混合检索与重排 · 带引用多轮对话 · 增量文档管理 · 评估体系",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(chat.router, prefix="/api")
app.include_router(documents.router, prefix="/api")

# 前端静态页(单页 HTML,无构建工具)
_static_dir = config.PROJECT_ROOT / "frontend" / "static"
if _static_dir.exists():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="frontend")
