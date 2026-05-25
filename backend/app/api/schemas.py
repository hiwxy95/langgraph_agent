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
