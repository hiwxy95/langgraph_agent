from __future__ import annotations

from typing import Any, Literal, TypedDict

from langgraph.graph.message import add_messages
from typing_extensions import Annotated


class PendingApproval(TypedDict, total=False):
    kind: Literal["itinerary_confirmation"]
    draft: str
    tool_results: dict[str, Any]
    question: str


class TravelAgentState(TypedDict, total=False):
    conversation_id: str
    messages: Annotated[list[Any], add_messages]
    user_profile: dict[str, Any]
    travel_requirements: dict[str, Any]
    tool_results: dict[str, Any]
    pending_approval: PendingApproval | None
    final_answer: str | None
    model_provider: str
    task_type: str
    route_target: str
    error: str | None
