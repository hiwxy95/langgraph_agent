from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.config import ModelProvider


class MessageOut(BaseModel):
    id: UUID | None = None
    role: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class ConversationOut(BaseModel):
    id: UUID
    title: str
    status: str
    created_at: datetime
    updated_at: datetime


class ConversationDetailOut(ConversationOut):
    messages: list[MessageOut] = Field(default_factory=list)
    pending_approval: dict[str, Any] | None = None


class CreateConversationRequest(BaseModel):
    title: str | None = None


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1)
    model_provider: ModelProvider = "auto"


class ApprovalRequest(BaseModel):
    action: Literal["approve", "revise", "cancel"]
    comment: str | None = None


class AgentResponse(BaseModel):
    conversation_id: UUID
    messages: list[MessageOut] = Field(default_factory=list)
    status: str
    requires_human_approval: bool = False
    approval_payload: dict[str, Any] | None = None
    error: str | None = None


class StreamEvent(BaseModel):
    event: Literal["start", "token", "message", "approval", "done", "error"]
    conversation_id: UUID
    message: MessageOut | None = None
    text: str | None = None
    status: str | None = None
    approval_payload: dict[str, Any] | None = None
    error: str | None = None


KnowledgeCategory = Literal[
    "tourism_material",
    "policy_document",
    "attraction_intro",
    "hotel_description",
]


class KnowledgeDocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    category: KnowledgeCategory
    content: str = Field(min_length=1)
    source_url: str | None = None


class KnowledgeDocumentOut(BaseModel):
    id: UUID
    title: str
    category: KnowledgeCategory
    source_type: str
    source_name: str | None = None
    source_url: str | None = None
    status: str
    chunk_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class KnowledgeChunkOut(BaseModel):
    id: UUID
    document_id: UUID
    chunk_index: int
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class KnowledgeDocumentDetailOut(KnowledgeDocumentOut):
    content: str
    chunks: list[KnowledgeChunkOut] = Field(default_factory=list)


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    category: KnowledgeCategory | None = None
    top_k: int = Field(default=5, ge=1, le=20)


class KnowledgeSearchResult(BaseModel):
    chunk_id: UUID
    document_id: UUID
    title: str
    category: KnowledgeCategory
    category_label: str
    chunk_index: int
    content: str
    similarity: float
    source_name: str | None = None
    source_url: str | None = None
