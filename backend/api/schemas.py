"""Pydantic 请求/响应模型。"""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, description="用户问题")
    session_id: str = Field(default="default", description="会话 id,同一会话保持多轮上下文")


class SourceInfo(BaseModel):
    source: str | None = None
    chunk_index: int | None = None
    doc_id: str | None = None
    retrieved_by: list[str] | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None  # 重排分数;重排关闭/降级时为 null,前端隐藏徽章
    text: str | None = None


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceInfo]
    session_id: str


class DocInfo(BaseModel):
    doc_id: str
    filename: str
    fmt: str
    num_chunks: int
    added_at: str
    uploaded_by: int | None = None   # 上传者;语料库文档为 null(全员可见)
    owner: str | None = None         # 上传者用户名,前端分组展示


class DocListResponse(BaseModel):
    documents: list[DocInfo]


class DocAddResponse(BaseModel):
    doc_id: str
    filename: str
    fmt: str
    num_chunks: int
    added_at: str


# ─── 模型设置(设置页) ────────────────────────────────────────────
# 注意:PUT 请求体里 api_key 是明文(仅前端→后端);GET 响应里一律掩码。

class LLMSettingsUpdate(BaseModel):
    provider: str | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    temperature: float | None = None


class EmbeddingSettingsUpdate(BaseModel):
    provider: str | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None


class RerankSettingsUpdate(BaseModel):
    enabled: bool | None = None
    provider: str | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None


class SettingsUpdate(BaseModel):
    llm: LLMSettingsUpdate | None = None
    embedding: EmbeddingSettingsUpdate | None = None
    rerank: RerankSettingsUpdate | None = None


class ConnectionTestRequest(BaseModel):
    """按给定候选配置测连接(不保存);留空的字段用当前生效配置。"""
    llm: LLMSettingsUpdate | None = None
    embedding: EmbeddingSettingsUpdate | None = None
    rerank: RerankSettingsUpdate | None = None


# ─── 登录鉴权 ────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class UserInfo(BaseModel):
    id: int
    username: str
    role: str  # admin | user


class AuthResponse(BaseModel):
    token: str
    user: UserInfo


# ─── 会话管理 ────────────────────────────────────────────────────

class SessionInfo(BaseModel):
    id: str
    title: str
    message_count: int
    updated_at: str


class SessionCreateResponse(BaseModel):
    id: str
    title: str


class MessageInfo(BaseModel):
    role: str
    content: str
    created_at: str


class SessionMessagesResponse(BaseModel):
    messages: list[MessageInfo]


# ─── 异步摄取任务 ────────────────────────────────────────────────

class TaskInfo(BaseModel):
    id: int
    filename: str
    status: str          # pending | running | done | failed
    progress: int
    error: str | None = None
    doc_id: str | None = None
    created_at: str


class TaskListResponse(BaseModel):
    tasks: list[TaskInfo]


class UploadResponse(BaseModel):
    task_id: int
    status: str
    doc_id: str | None = None
