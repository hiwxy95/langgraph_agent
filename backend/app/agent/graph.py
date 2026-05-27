from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import create_react_agent
from langgraph.types import Command, interrupt

from app.agent.prompts import DRAFT_PROMPT, FINAL_PROMPT, REACT_PROMPT, SYSTEM_PROMPT
from app.agent.state import TravelAgentState
from app.core.config import ModelProvider, Settings, get_settings
from app.llm.router import LLMRouter
from app.mcp.amap import AmapMCPClient, normalize_tool_content

RAG_PROMPT = (
    "回答时请优先参考“知识库依据”。如果依据不足，请明确说明哪些信息来自资料、"
    "哪些需要进一步确认。回答末尾用“依据：”简洁列出使用到的文档标题和片段编号。"
)


class TravelAgent:
    def __init__(
        self,
        settings: Settings | None = None,
        llm_router: LLMRouter | None = None,
        amap_client: AmapMCPClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.llm_router = llm_router or LLMRouter(self.settings)
        self.amap_client = amap_client or AmapMCPClient(self.settings)

    async def run(
        self,
        conversation_id: str,
        user_message: str,
        model_provider: ModelProvider = "auto",
        history_messages: list[Any] | None = None,
        knowledge_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        async with self._compiled_graph() as graph:
            config = self._thread_config(conversation_id)
            result = await graph.ainvoke(
                {
                    "conversation_id": conversation_id,
                    "messages": await self._input_messages_for_graph(
                        graph, config, history_messages, user_message
                    ),
                    "model_provider": model_provider,
                    "knowledge_context": knowledge_context or {},
                },
                config=config,
            )
            return self._to_response(result)

    async def run_stream(
        self,
        conversation_id: str,
        user_message: str,
        model_provider: ModelProvider = "auto",
        history_messages: list[Any] | None = None,
        knowledge_context: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        async with self._compiled_graph() as graph:
            config = self._thread_config(conversation_id)
            input_messages = await self._input_messages_for_stream(
                graph, config, history_messages, user_message
            )

            state: TravelAgentState = {
                "conversation_id": conversation_id,
                "messages": input_messages,
                "model_provider": model_provider,
                "knowledge_context": knowledge_context or {},
            }
            state.update(await self._classify_input(state))

            if state.get("route_target") == "react_reasoning":
                state.update(await self._react_reasoning(state))
                async for event in self._draft_itinerary_stream(state):
                    if event.get("event") == "message":
                        await self._persist_stream_checkpoint(
                            graph, config, state, input_messages, event.get("message")
                        )
                    yield event
                yield {
                    "event": "approval",
                    "conversation_id": conversation_id,
                    "approval_payload": state.get("pending_approval"),
                    "status": "awaiting_human",
                }
                return

            async for event in self._final_response_stream(state):
                if event.get("event") == "message":
                    await self._persist_stream_checkpoint(
                        graph, config, state, input_messages, event.get("message")
                    )
                yield event

    async def resume(
        self,
        conversation_id: str,
        action: Literal["approve", "revise", "cancel"],
        comment: str | None = None,
    ) -> dict[str, Any]:
        async with self._compiled_graph() as graph:
            result = await graph.ainvoke(
                Command(resume={"action": action, "comment": comment or ""}),
                config=self._thread_config(conversation_id),
            )
            return self._to_response(result)

    async def finalize_approval(
        self,
        conversation_id: str,
        draft: str,
        action: Literal["approve", "revise", "cancel"],
        comment: str | None = None,
        model_provider: ModelProvider = "auto",
    ) -> dict[str, Any]:
        state: TravelAgentState = {
            "conversation_id": conversation_id,
            "messages": [],
            "model_provider": model_provider,
            "knowledge_context": {},
            "pending_approval": {
                "kind": "itinerary_confirmation",
                "draft": draft,
                "review": {"action": action, "comment": comment or ""},
            },
        }
        content, metadata = await self._compose_final(state)
        return {
            "conversation_id": conversation_id,
            "messages": [AIMessage(content=content, additional_kwargs=metadata)],
            "status": "completed",
            "requires_human_approval": False,
            "approval_payload": None,
            "error": None,
            "final_answer": content,
        }

    @asynccontextmanager
    async def _compiled_graph(self) -> AsyncIterator[Any]:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        async with AsyncPostgresSaver.from_conn_string(
            self.settings.checkpoint_url
        ) as checkpointer:
            workflow = StateGraph(TravelAgentState)
            workflow.add_node("classify_input", self._classify_input)
            workflow.add_node("react_reasoning", self._react_reasoning)
            workflow.add_node("draft_itinerary", self._draft_itinerary)
            workflow.add_node("human_review", self._human_review)
            workflow.add_node("final_response", self._final_response)

            workflow.add_edge(START, "classify_input")
            workflow.add_conditional_edges(
                "classify_input",
                self._route_after_classify,
                {
                    "react_reasoning": "react_reasoning",
                    "final_response": "final_response",
                },
            )
            workflow.add_edge("react_reasoning", "draft_itinerary")
            workflow.add_edge("draft_itinerary", "human_review")
            workflow.add_edge("human_review", "final_response")
            workflow.add_edge("final_response", END)

            yield workflow.compile(checkpointer=checkpointer)

    async def _classify_input(self, state: TravelAgentState) -> dict[str, Any]:
        latest = _latest_user_text(state)
        planning_keywords = (
            "路线",
            "路径",
            "规划",
            "行程",
            "酒店",
            "住宿",
            "景点",
            "游玩",
            "怎么去",
            "旅游",
            "文旅",
        )
        should_plan = any(keyword in latest for keyword in planning_keywords)
        return {
            "task_type": "itinerary_planning" if should_plan else "chat",
            "route_target": "react_reasoning" if should_plan else "final_response",
        }

    def _route_after_classify(self, state: TravelAgentState) -> str:
        return state.get("route_target", "final_response")

    async def _react_reasoning(self, state: TravelAgentState) -> dict[str, Any]:
        tools = await self.amap_client.as_langchain_tools()
        model = self.llm_router.chat_model(
            task_type="react_reasoning",
            model_provider=state.get("model_provider", "auto"),  # type: ignore[arg-type]
            hints={"requires_reasoning": True, "multi_step": True},
        )
        agent = create_react_agent(
            model,
            tools,
            prompt=SystemMessage(content=f"{SYSTEM_PROMPT}\n\n{REACT_PROMPT}"),
        )
        result = await agent.ainvoke({"messages": state.get("messages", [])})
        messages = result.get("messages", [])
        tool_results = _collect_tool_results(messages)
        if not tool_results:
            tool_results = {
                "notice": "未调用地图工具，可能是用户需求还缺少城市、地点或日期。"
            }
        return {"messages": messages, "tool_results": tool_results}

    async def _draft_itinerary(self, state: TravelAgentState) -> dict[str, Any]:
        content, metadata = await self._compose_draft(state)
        return {
            "messages": [AIMessage(content=content, additional_kwargs=metadata)],
            "pending_approval": {
                "kind": "itinerary_confirmation",
                "draft": content,
                "tool_results": state.get("tool_results") or {},
                "question": "请确认是否采用这份文旅方案，或补充你想修改的地方。",
            },
        }

    async def _draft_itinerary_stream(
        self, state: TravelAgentState
    ) -> AsyncIterator[dict[str, Any]]:
        content_parts: list[str] = []
        metadata: dict[str, Any] = {}

        async for kind, payload in self._stream_draft(state):
            if kind == "token":
                text = str(payload)
                content_parts.append(text)
                yield {
                    "event": "token",
                    "conversation_id": state["conversation_id"],
                    "text": text,
                }
            else:
                metadata = payload

        content = "".join(content_parts)
        ai_message = AIMessage(content=content, additional_kwargs=metadata)
        state["pending_approval"] = {
            "kind": "itinerary_confirmation",
            "draft": content,
            "tool_results": state.get("tool_results") or {},
            "question": "请确认是否采用这份文旅方案，或补充你想修改的地方。",
        }
        yield {
            "event": "message",
            "conversation_id": state["conversation_id"],
            "message": ai_message,
            "status": "awaiting_human",
        }

    async def _human_review(self, state: TravelAgentState) -> dict[str, Any]:
        pending = state.get("pending_approval")
        if not pending:
            return {}
        review = interrupt(pending)
        return {"pending_approval": {**pending, "review": review}}

    async def _final_response(self, state: TravelAgentState) -> dict[str, Any]:
        content, metadata = await self._compose_final(state)
        return {
            "messages": [AIMessage(content=content, additional_kwargs=metadata)],
            "final_answer": content,
            "pending_approval": None,
        }

    async def _final_response_stream(
        self, state: TravelAgentState
    ) -> AsyncIterator[dict[str, Any]]:
        content_parts: list[str] = []
        metadata: dict[str, Any] = {}

        async for kind, payload in self._stream_final(state):
            if kind == "token":
                text = str(payload)
                content_parts.append(text)
                yield {
                    "event": "token",
                    "conversation_id": state["conversation_id"],
                    "text": text,
                }
            else:
                metadata = payload

        content = "".join(content_parts)
        yield {
            "event": "message",
            "conversation_id": state["conversation_id"],
            "message": AIMessage(content=content, additional_kwargs=metadata),
            "status": "completed",
        }
        yield {
            "event": "done",
            "conversation_id": state["conversation_id"],
            "status": "completed",
        }

    async def _compose_draft(
        self, state: TravelAgentState
    ) -> tuple[str, dict[str, Any]]:
        content_parts: list[str] = []
        metadata: dict[str, Any] = {}
        async for kind, payload in self._stream_draft(state):
            if kind == "token":
                content_parts.append(str(payload))
            else:
                metadata = payload
        return "".join(content_parts), metadata

    async def _compose_final(
        self, state: TravelAgentState
    ) -> tuple[str, dict[str, Any]]:
        content_parts: list[str] = []
        metadata: dict[str, Any] = {}
        async for kind, payload in self._stream_final(state):
            if kind == "token":
                content_parts.append(str(payload))
            else:
                metadata = payload
        return "".join(content_parts), metadata

    async def _stream_draft(
        self, state: TravelAgentState
    ) -> AsyncIterator[tuple[str, str | dict[str, Any]]]:
        tool_results = state.get("tool_results") or {}
        messages = [
            SystemMessage(content=f"{SYSTEM_PROMPT}\n\n{DRAFT_PROMPT}"),
            HumanMessage(
                content=(
                    "用户历史消息：\n"
                    f"{_messages_as_text(state.get('messages', []))}\n\n"
                    "工具查询结果：\n"
                    f"{json.dumps(tool_results, ensure_ascii=False, indent=2, default=str)}"
                )
            ),
        ]
        knowledge_text = _knowledge_context_text(state)
        if knowledge_text:
            messages.insert(
                1,
                SystemMessage(content=f"{RAG_PROMPT}\n\n知识库依据：\n{knowledge_text}"),
            )

        async for kind, payload in self.llm_router.stream(
            messages,
            task_type="itinerary_planning",
            hints={"requires_reasoning": True, "multi_step": True},
            model_provider=state.get("model_provider", "auto"),  # type: ignore[arg-type]
        ):
            if kind == "token":
                yield ("token", str(payload))
            else:
                result = payload
                yield (
                    "metadata",
                    {
                        "provider": result.provider,
                        "model": result.model,
                        "fallback_from": result.fallback_from,
                        "knowledge_sources": _knowledge_sources(state),
                    },
                )

    async def _stream_final(
        self, state: TravelAgentState
    ) -> AsyncIterator[tuple[str, str | dict[str, Any]]]:
        review = (state.get("pending_approval") or {}).get("review")
        if not review:
            system_content = f"{SYSTEM_PROMPT}\n\n{RAG_PROMPT}"
            knowledge_text = _knowledge_context_text(state)
            if knowledge_text:
                system_content = f"{system_content}\n\n知识库依据：\n{knowledge_text}"
            messages = [SystemMessage(content=system_content), *state.get("messages", [])]
            async for kind, payload in self.llm_router.stream(
                messages,
                task_type="chat",
                model_provider=state.get("model_provider", "auto"),  # type: ignore[arg-type]
            ):
                if kind == "token":
                    yield ("token", str(payload))
                else:
                    result = payload
                    yield (
                        "metadata",
                        {
                            "provider": result.provider,
                            "model": result.model,
                            "fallback_from": result.fallback_from,
                            "knowledge_sources": _knowledge_sources(state),
                        },
                    )
            return

        review_text = json.dumps(review, ensure_ascii=False, indent=2)
        messages = [
            SystemMessage(content=f"{SYSTEM_PROMPT}\n\n{FINAL_PROMPT}"),
            HumanMessage(
                content=(
                    f"待确认草案：\n{state.get('pending_approval', {}).get('draft', '')}\n\n"
                    f"用户确认结果：\n{review_text}"
                )
            ),
        ]
        async for kind, payload in self.llm_router.stream(
            messages,
            task_type="itinerary_planning",
            hints={"requires_reasoning": True},
            model_provider=state.get("model_provider", "auto"),  # type: ignore[arg-type]
        ):
            if kind == "token":
                yield ("token", str(payload))
            else:
                result = payload
                yield (
                    "metadata",
                    {
                        "provider": result.provider,
                        "model": result.model,
                        "fallback_from": result.fallback_from,
                        "knowledge_sources": _knowledge_sources(state),
                    },
                )

    @staticmethod
    def _thread_config(conversation_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": conversation_id}}

    async def _input_messages_for_graph(
        self,
        graph: Any,
        config: dict[str, Any],
        history_messages: list[Any] | None,
        user_message: str,
    ) -> list[Any]:
        if await _checkpoint_has_messages(graph, config):
            return [HumanMessage(content=user_message)]
        return _compose_message_context(history_messages, user_message)

    async def _input_messages_for_stream(
        self,
        graph: Any,
        config: dict[str, Any],
        history_messages: list[Any] | None,
        user_message: str,
    ) -> list[Any]:
        checkpoint_messages = await _checkpoint_messages(graph, config)
        if checkpoint_messages:
            return _compose_message_context(checkpoint_messages, user_message)
        return _compose_message_context(history_messages, user_message)

    async def _persist_stream_checkpoint(
        self,
        graph: Any,
        config: dict[str, Any],
        state: TravelAgentState,
        input_messages: list[Any],
        ai_message: Any,
    ) -> None:
        if not isinstance(ai_message, AIMessage):
            return

        messages = [HumanMessage(content=_latest_user_text({"messages": input_messages}))]
        if not await _checkpoint_has_messages(graph, config):
            messages = list(input_messages)
        messages.append(ai_message)

        await graph.aupdate_state(
            config,
            {
                "conversation_id": state.get("conversation_id"),
                "messages": messages,
                "model_provider": state.get("model_provider"),
                "task_type": state.get("task_type"),
                "route_target": state.get("route_target"),
                "tool_results": state.get("tool_results") or {},
                "knowledge_context": state.get("knowledge_context") or {},
                "pending_approval": state.get("pending_approval"),
                "final_answer": str(ai_message.content),
            },
            as_node="final_response",
        )

    @staticmethod
    def _to_response(result: dict[str, Any]) -> dict[str, Any]:
        interrupts = result.get("__interrupt__") or []
        interrupt_payload = interrupts[0].value if interrupts else None
        pending = interrupt_payload or result.get("pending_approval")
        return {
            "conversation_id": result.get("conversation_id"),
            "messages": result.get("messages", []),
            "status": "awaiting_human" if pending else "completed",
            "requires_human_approval": bool(pending),
            "approval_payload": pending,
            "error": result.get("error"),
            "final_answer": result.get("final_answer"),
        }


def _latest_user_text(state: TravelAgentState) -> str:
    for message in reversed(state.get("messages", [])):
        if isinstance(message, HumanMessage):
            return str(message.content)
        if getattr(message, "type", "") == "human":
            return str(getattr(message, "content", ""))
    return ""


def _compose_message_context(
    history_messages: list[Any] | None, user_message: str
) -> list[Any]:
    messages = list(history_messages or [])
    if not messages or not (
        isinstance(messages[-1], HumanMessage)
        and str(messages[-1].content) == user_message
    ):
        messages.append(HumanMessage(content=user_message))
    return messages


def _messages_as_text(messages: list[Any]) -> str:
    lines: list[str] = []
    for message in messages:
        role = getattr(message, "type", message.__class__.__name__)
        content = getattr(message, "content", "")
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _knowledge_context_text(state: TravelAgentState) -> str:
    context = state.get("knowledge_context") or {}
    return str(context.get("text") or "").strip()


def _knowledge_sources(state: TravelAgentState) -> list[dict[str, Any]]:
    context = state.get("knowledge_context") or {}
    sources = context.get("sources") or []
    if isinstance(sources, list):
        return [source for source in sources if isinstance(source, dict)]
    return []


async def _checkpoint_has_messages(graph: Any, config: dict[str, Any]) -> bool:
    return bool(await _checkpoint_messages(graph, config))


async def _checkpoint_messages(graph: Any, config: dict[str, Any]) -> list[Any]:
    try:
        snapshot = await graph.aget_state(config)
    except Exception:
        return []
    values = snapshot.values if isinstance(snapshot.values, dict) else {}
    messages = values.get("messages") or []
    return list(messages)


def _collect_tool_results(messages: list[Any]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for message in messages:
        if getattr(message, "type", "") == "tool":
            name = getattr(message, "name", "tool")
            results[name] = normalize_tool_content(getattr(message, "content", ""))
    return results
