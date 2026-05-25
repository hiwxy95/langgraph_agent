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
    ) -> dict[str, Any]:
        async with self._compiled_graph() as graph:
            result = await graph.ainvoke(
                {
                    "conversation_id": conversation_id,
                    "messages": [HumanMessage(content=user_message)],
                    "model_provider": model_provider,
                },
                config=self._thread_config(conversation_id),
            )
            return self._to_response(result)

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

    @asynccontextmanager
    async def _compiled_graph(self) -> AsyncIterator[Any]:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        async with AsyncPostgresSaver.from_conn_string(self.settings.checkpoint_url) as checkpointer:
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
            "怎么走",
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
        routed = await self.llm_router.invoke(
            messages,
            task_type="itinerary_planning",
            hints={"requires_reasoning": True, "multi_step": True},
            model_provider=state.get("model_provider", "auto"),  # type: ignore[arg-type]
        )
        draft = routed.content
        metadata = {
            "provider": routed.provider,
            "model": routed.model,
            "fallback_from": routed.fallback_from,
        }
        return {
            "messages": [AIMessage(content=draft, additional_kwargs=metadata)],
            "pending_approval": {
                "kind": "itinerary_confirmation",
                "draft": draft,
                "tool_results": tool_results,
                "question": "请确认是否采用这份文旅方案，或补充你想修改的地方。",
            },
        }

    async def _human_review(self, state: TravelAgentState) -> dict[str, Any]:
        pending = state.get("pending_approval")
        if not pending:
            return {}
        review = interrupt(pending)
        return {"pending_approval": {**pending, "review": review}}

    async def _final_response(self, state: TravelAgentState) -> dict[str, Any]:
        review = (state.get("pending_approval") or {}).get("review")
        if not review:
            routed = await self.llm_router.invoke(
                [SystemMessage(content=SYSTEM_PROMPT), *state.get("messages", [])],
                task_type="chat",
                model_provider=state.get("model_provider", "auto"),  # type: ignore[arg-type]
            )
            return {
                "messages": [
                    AIMessage(
                        content=routed.content,
                        additional_kwargs={
                            "provider": routed.provider,
                            "model": routed.model,
                            "fallback_from": routed.fallback_from,
                        },
                    )
                ],
                "final_answer": routed.content,
                "pending_approval": None,
            }

        review_text = json.dumps(review, ensure_ascii=False, indent=2)
        routed = await self.llm_router.invoke(
            [
                SystemMessage(content=f"{SYSTEM_PROMPT}\n\n{FINAL_PROMPT}"),
                HumanMessage(
                    content=(
                        f"待确认草案：\n{state.get('pending_approval', {}).get('draft', '')}\n\n"
                        f"用户确认结果：\n{review_text}"
                    )
                ),
            ],
            task_type="itinerary_planning",
            hints={"requires_reasoning": True},
            model_provider=state.get("model_provider", "auto"),  # type: ignore[arg-type]
        )
        return {
            "messages": [
                AIMessage(
                    content=routed.content,
                    additional_kwargs={
                        "provider": routed.provider,
                        "model": routed.model,
                        "fallback_from": routed.fallback_from,
                    },
                )
            ],
            "final_answer": routed.content,
            "pending_approval": None,
        }

    @staticmethod
    def _thread_config(conversation_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": conversation_id}}

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


def _messages_as_text(messages: list[Any]) -> str:
    lines: list[str] = []
    for message in messages:
        role = getattr(message, "type", message.__class__.__name__)
        content = getattr(message, "content", "")
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _collect_tool_results(messages: list[Any]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for message in messages:
        if getattr(message, "type", "") == "tool":
            name = getattr(message, "name", "tool")
            results[name] = normalize_tool_content(getattr(message, "content", ""))
    return results
