import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agent.graph import TravelAgent, _checkpoint_messages, _compose_message_context


class DummySnapshot:
    def __init__(self, values):
        self.values = values


class DummyGraph:
    def __init__(self, messages=None, fail=False):
        self.messages = messages or []
        self.fail = fail

    async def aget_state(self, config):
        if self.fail:
            raise RuntimeError("checkpoint unavailable")
        return DummySnapshot({"messages": self.messages})


def test_compose_message_context_keeps_history_and_appends_current_user() -> None:
    history = [
        HumanMessage(content="I want to drive from Shenzhen to Shantou for 3 days."),
        AIMessage(content="OK, I will draft a 3-day itinerary."),
    ]

    messages = _compose_message_context(history, "Medium budget.")

    assert [message.content for message in messages] == [
        "I want to drive from Shenzhen to Shantou for 3 days.",
        "OK, I will draft a 3-day itinerary.",
        "Medium budget.",
    ]


def test_compose_message_context_does_not_duplicate_current_user_message() -> None:
    history = [HumanMessage(content="Medium budget.")]

    messages = _compose_message_context(history, "Medium budget.")

    assert len(messages) == 1
    assert messages[0].content == "Medium budget."


@pytest.mark.asyncio
async def test_graph_input_uses_only_current_message_when_checkpoint_exists() -> None:
    agent = TravelAgent.__new__(TravelAgent)
    graph = DummyGraph([HumanMessage(content="I want to travel for three days.")])

    messages = await agent._input_messages_for_graph(
        graph,
        {"configurable": {"thread_id": "test"}},
        [HumanMessage(content="old db history")],
        "Medium budget.",
    )

    assert [message.content for message in messages] == ["Medium budget."]


@pytest.mark.asyncio
async def test_stream_input_merges_checkpoint_messages() -> None:
    agent = TravelAgent.__new__(TravelAgent)
    graph = DummyGraph(
        [
            HumanMessage(content="I want to travel for three days."),
            AIMessage(content="Drafting a three day plan."),
        ]
    )

    messages = await agent._input_messages_for_stream(
        graph,
        {"configurable": {"thread_id": "test"}},
        [HumanMessage(content="old db history")],
        "Medium budget.",
    )

    assert [message.content for message in messages] == [
        "I want to travel for three days.",
        "Drafting a three day plan.",
        "Medium budget.",
    ]


@pytest.mark.asyncio
async def test_checkpoint_messages_falls_back_to_empty_list() -> None:
    messages = await _checkpoint_messages(
        DummyGraph(fail=True), {"configurable": {"thread_id": "test"}}
    )

    assert messages == []
