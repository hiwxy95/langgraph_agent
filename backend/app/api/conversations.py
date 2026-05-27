from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage
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
from app.rag.service import KnowledgeService, build_rag_context

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
        (
            approval.payload
            for approval in reversed(conversation.approvals)
            if approval.status == "pending"
        ),
        None,
    )
    return ConversationDetailOut(
        **_conversation_out(conversation).model_dump(),
        messages=[_message_out(message) for message in conversation.messages],
        pending_approval=pending,
    )


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    deleted = await repository.delete_conversation(session, conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    await _delete_langgraph_thread(str(conversation_id))


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
    knowledge_context = await _rag_context_for_message(session, request.content)

    agent = TravelAgent()
    try:
        result = await agent.run(
            str(conversation_id),
            request.content,
            request.model_provider,
            history_messages=_history_to_langchain_messages(conversation.messages),
            knowledge_context=knowledge_context,
        )
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

    return await _persist_agent_response(session, conversation_id, result)


@router.post("/{conversation_id}/messages/stream")
async def stream_message(
    conversation_id: uuid.UUID,
    request: SendMessageRequest,
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    conversation = await repository.get_conversation(session, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    await repository.add_message(session, conversation_id, "user", request.content)
    knowledge_context = await _rag_context_for_message(session, request.content)
    agent = TravelAgent()

    async def event_stream() -> AsyncIterator[str]:
        assistant_text_parts: list[str] = []
        assistant_metadata: dict[str, Any] = {}
        approval_payload: dict[str, Any] | None = None
        status = "completed"

        yield _sse_payload(
            {
                "event": "start",
                "conversation_id": str(conversation_id),
                "status": "streaming",
            }
        )

        try:
            async for event in agent.run_stream(
                str(conversation_id),
                request.content,
                request.model_provider,
                history_messages=_history_to_langchain_messages(conversation.messages),
                knowledge_context=knowledge_context,
            ):
                event_name = event.get("event")
                if event_name == "token":
                    text = str(event.get("text", ""))
                    assistant_text_parts.append(text)
                    yield _sse_payload(
                        {
                            "event": "token",
                            "conversation_id": str(conversation_id),
                            "text": text,
                        }
                    )
                    continue

                if event_name == "message":
                    ai_message = event.get("message")
                    if isinstance(ai_message, AIMessage):
                        assistant_metadata = dict(ai_message.additional_kwargs or {})
                        saved = await repository.add_message(
                            session,
                            conversation_id,
                            "assistant",
                            str(ai_message.content),
                            assistant_metadata,
                        )
                        yield _sse_payload(
                            {
                                "event": "message",
                                "conversation_id": str(conversation_id),
                                "message": _message_out(saved).model_dump(mode="json"),
                                "status": event.get("status", "completed"),
                            }
                        )
                    continue

                if event_name == "approval":
                    approval_payload = event.get("approval_payload")
                    status = event.get("status", "awaiting_human")
                    if approval_payload:
                        approval = await repository.latest_pending_approval(
                            session, conversation_id
                        )
                        if not approval:
                            approval = await repository.create_approval(
                                session, conversation_id, approval_payload
                            )
                        approval_payload = {
                            "approval_id": str(approval.id),
                            **approval.payload,
                        }
                    yield _sse_payload(
                        {
                            "event": "approval",
                            "conversation_id": str(conversation_id),
                            "approval_payload": approval_payload,
                            "status": status,
                        }
                    )
                    continue

                if event_name == "done":
                    status = event.get("status", "completed")
                    yield _sse_payload(
                        {
                            "event": "done",
                            "conversation_id": str(conversation_id),
                            "status": status,
                        }
                    )
        except Exception as exc:
            await repository.add_message(
                session,
                conversation_id,
                "assistant",
                f"抱歉，智能体执行失败：{exc}",
                {"error": str(exc)},
            )
            yield _sse_payload(
                {
                    "event": "error",
                    "conversation_id": str(conversation_id),
                    "error": str(exc),
                    "status": "failed",
                }
            )
            return

        if approval_payload:
            await repository.set_conversation_status(session, conversation_id, "awaiting_human")
        else:
            await repository.set_conversation_status(session, conversation_id, status)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


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
    draft = str(approval.payload.get("draft", ""))
    if draft:
        result = await agent.finalize_approval(
            conversation_id=str(conversation_id),
            draft=draft,
            action=request.action,
            comment=request.comment,
        )
    else:
        try:
            result = await agent.resume(
                conversation_id=str(conversation_id),
                action=request.action,
                comment=request.comment,
            )
        except Exception:
            result = await agent.finalize_approval(
                conversation_id=str(conversation_id),
                draft="",
                action=request.action,
                comment=request.comment,
            )

    return await _persist_agent_response(session, conversation_id, result)


async def _persist_agent_response(
    session: AsyncSession, conversation_id: uuid.UUID, result: dict[str, Any]
) -> AgentResponse:
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
            approval = await repository.create_approval(
                session, conversation_id, approval_payload
            )
        approval_payload = {"approval_id": str(approval.id), **approval.payload}
    else:
        await repository.set_conversation_status(
            session, conversation_id, result.get("status", "active")
        )

    return AgentResponse(
        conversation_id=conversation_id,
        messages=saved_messages,
        status=result.get("status", "completed"),
        requires_human_approval=bool(result.get("requires_human_approval")),
        approval_payload=approval_payload,
        error=result.get("error"),
    )


def _sse_payload(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


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


def _history_to_langchain_messages(messages: list[Message]) -> list[Any]:
    converted: list[Any] = []
    for message in messages:
        if message.role == "user":
            converted.append(HumanMessage(content=message.content))
        elif message.role == "assistant":
            converted.append(AIMessage(content=message.content))
    return converted


async def _rag_context_for_message(
    session: AsyncSession, content: str
) -> dict[str, Any]:
    service = KnowledgeService(session)
    if not await service.has_active_documents():
        return {}
    context = build_rag_context(await service.search(content))
    return {"text": context.text, "sources": context.sources}


async def _delete_langgraph_thread(conversation_id: str) -> None:
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        from app.core.config import get_settings

        async with AsyncPostgresSaver.from_conn_string(
            get_settings().checkpoint_url
        ) as checkpointer:
            delete_thread = getattr(checkpointer, "adelete_thread", None)
            if delete_thread:
                await delete_thread(conversation_id)
    except Exception:
        return
