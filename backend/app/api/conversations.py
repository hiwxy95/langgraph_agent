from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from langchain_core.messages import AIMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import TravelAgent
from app.api.schemas import (
    AgentResponse,
    ApprovalRequest,
    ConversationDetailOut,
    ConversationOut,
    CreateConversationRequest,
    MessageOut,
    SendMessageRequest,
)
from app.db import repository
from app.db.models import Conversation, Message
from app.db.session import get_session

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("", response_model=ConversationOut)
async def create_conversation(
    request: CreateConversationRequest,
    session: AsyncSession = Depends(get_session),
) -> ConversationOut:
    conversation = await repository.create_conversation(session, request.title)
    return _conversation_out(conversation)


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    session: AsyncSession = Depends(get_session),
) -> list[ConversationOut]:
    conversations = await repository.list_conversations(session)
    return [_conversation_out(conversation) for conversation in conversations]


@router.get("/{conversation_id}", response_model=ConversationDetailOut)
async def get_conversation(
    conversation_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> ConversationDetailOut:
    conversation = await repository.get_conversation(session, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    pending = next(
        (approval.payload for approval in reversed(conversation.approvals) if approval.status == "pending"),
        None,
    )
    return ConversationDetailOut(
        **_conversation_out(conversation).model_dump(),
        messages=[_message_out(message) for message in conversation.messages],
        pending_approval=pending,
    )


@router.post("/{conversation_id}/messages", response_model=AgentResponse)
async def send_message(
    conversation_id: uuid.UUID,
    request: SendMessageRequest,
    session: AsyncSession = Depends(get_session),
) -> AgentResponse:
    conversation = await repository.get_conversation(session, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    await repository.add_message(session, conversation_id, "user", request.content)

    agent = TravelAgent()
    try:
        result = await agent.run(str(conversation_id), request.content, request.model_provider)
    except Exception as exc:
        await repository.add_message(
            session,
            conversation_id,
            "assistant",
            f"抱歉，智能体执行失败：{exc}",
            {"error": str(exc)},
        )
        return AgentResponse(
            conversation_id=conversation_id,
            messages=[],
            status="failed",
            error=str(exc),
        )

    ai_messages = _extract_new_ai_messages(result.get("messages", []))
    saved_messages: list[MessageOut] = []
    for ai_message in ai_messages:
        saved = await repository.add_message(
            session,
            conversation_id,
            "assistant",
            str(ai_message.content),
            dict(ai_message.additional_kwargs or {}),
        )
        saved_messages.append(_message_out(saved))

    approval_payload = result.get("approval_payload")
    if result.get("requires_human_approval") and approval_payload:
        approval = await repository.latest_pending_approval(session, conversation_id)
        if not approval:
            approval = await repository.create_approval(session, conversation_id, approval_payload)
        approval_payload = {"approval_id": str(approval.id), **approval.payload}
    else:
        await repository.set_conversation_status(session, conversation_id, "active")

    return AgentResponse(
        conversation_id=conversation_id,
        messages=saved_messages,
        status=result.get("status", "completed"),
        requires_human_approval=bool(result.get("requires_human_approval")),
        approval_payload=approval_payload,
        error=result.get("error"),
    )


@router.post("/{conversation_id}/approvals", response_model=AgentResponse)
async def submit_approval(
    conversation_id: uuid.UUID,
    request: ApprovalRequest,
    session: AsyncSession = Depends(get_session),
) -> AgentResponse:
    conversation = await repository.get_conversation(session, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    approval = await repository.latest_pending_approval(session, conversation_id)
    if not approval:
        raise HTTPException(status_code=409, detail="No pending human approval.")

    status = "approved" if request.action in {"approve", "revise"} else "cancelled"
    await repository.complete_approval(
        session,
        approval,
        {"action": request.action, "comment": request.comment or ""},
        status,
    )

    if request.action == "cancel":
        message = await repository.add_message(
            session,
            conversation_id,
            "assistant",
            "已取消本次规划。你可以随时补充新的目的地、日期或偏好，我再继续帮你规划。",
            {"approval_action": request.action},
        )
        await repository.set_conversation_status(session, conversation_id, "cancelled")
        return AgentResponse(
            conversation_id=conversation_id,
            messages=[_message_out(message)],
            status="cancelled",
            requires_human_approval=False,
        )

    agent = TravelAgent()
    try:
        result = await agent.resume(conversation_id=str(conversation_id), action=request.action, comment=request.comment)
    except Exception as exc:
        return AgentResponse(
            conversation_id=conversation_id,
            messages=[],
            status="failed",
            error=str(exc),
        )

    ai_messages = _extract_new_ai_messages(result.get("messages", []))
    saved_messages: list[MessageOut] = []
    for ai_message in ai_messages:
        saved = await repository.add_message(
            session,
            conversation_id,
            "assistant",
            str(ai_message.content),
            dict(ai_message.additional_kwargs or {}),
        )
        saved_messages.append(_message_out(saved))

    return AgentResponse(
        conversation_id=conversation_id,
        messages=saved_messages,
        status=result.get("status", "completed"),
        requires_human_approval=bool(result.get("requires_human_approval")),
        approval_payload=result.get("approval_payload"),
        error=result.get("error"),
    )


def _conversation_out(conversation: Conversation) -> ConversationOut:
    return ConversationOut(
        id=conversation.id,
        title=conversation.title,
        status=conversation.status,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def _message_out(message: Message) -> MessageOut:
    return MessageOut(
        id=message.id,
        role=message.role,
        content=message.content,
        metadata=message.message_metadata or {},
        created_at=message.created_at,
    )


def _extract_new_ai_messages(messages: list[Any]) -> list[AIMessage]:
    ai_messages = [message for message in messages if isinstance(message, AIMessage)]
    if not ai_messages:
        return []
    return [ai_messages[-1]]
