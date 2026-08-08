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


class DocListResponse(BaseModel):
    documents: list[DocInfo]


class DocAddResponse(BaseModel):
    doc_id: str
    filename: str
    fmt: str
    num_chunks: int
    added_at: str
