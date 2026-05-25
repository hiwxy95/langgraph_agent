from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Select, desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Conversation, HumanApproval, Message


async def create_conversation(session: AsyncSession, title: str | None = None) -> Conversation:
    conversation = Conversation(title=title or "新的文旅对话")
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return conversation


async def list_conversations(session: AsyncSession) -> list[Conversation]:
    stmt: Select[tuple[Conversation]] = (
        select(Conversation).order_by(desc(Conversation.updated_at)).limit(100)
    )
    return list((await session.scalars(stmt)).all())


async def get_conversation(
    session: AsyncSession, conversation_id: uuid.UUID
) -> Conversation | None:
    stmt = (
        select(Conversation)
        .options(selectinload(Conversation.messages), selectinload(Conversation.approvals))
        .where(Conversation.id == conversation_id)
    )
    return await session.scalar(stmt)


async def add_message(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    role: str,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> Message:
    message = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        message_metadata=metadata or {},
    )
    session.add(message)
    conversation = await session.get(Conversation, conversation_id)
    if conversation:
        conversation.status = "active"
    await session.commit()
    await session.refresh(message)
    return message


async def set_conversation_status(
    session: AsyncSession, conversation_id: uuid.UUID, status: str
) -> None:
    conversation = await session.get(Conversation, conversation_id)
    if conversation:
        conversation.status = status
        await session.commit()


async def create_approval(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    payload: dict[str, Any],
) -> HumanApproval:
    approval = HumanApproval(conversation_id=conversation_id, payload=payload)
    session.add(approval)
    conversation = await session.get(Conversation, conversation_id)
    if conversation:
        conversation.status = "awaiting_human"
    await session.commit()
    await session.refresh(approval)
    return approval


async def latest_pending_approval(
    session: AsyncSession, conversation_id: uuid.UUID
) -> HumanApproval | None:
    stmt = (
        select(HumanApproval)
        .where(
            HumanApproval.conversation_id == conversation_id,
            HumanApproval.status == "pending",
        )
        .order_by(desc(HumanApproval.created_at))
        .limit(1)
    )
    return await session.scalar(stmt)


async def complete_approval(
    session: AsyncSession,
    approval: HumanApproval,
    response: dict[str, Any],
    status: str,
) -> HumanApproval:
    approval.response = response
    approval.status = status
    conversation = await session.get(Conversation, approval.conversation_id)
    if conversation:
        conversation.status = "active" if status == "approved" else "cancelled"
    await session.commit()
    await session.refresh(approval)
    return approval
