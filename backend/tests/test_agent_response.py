from types import SimpleNamespace

from app.agent.graph import TravelAgent


def test_interrupt_payload_maps_to_human_approval_response() -> None:
    response = TravelAgent._to_response(
        {
            "conversation_id": "conversation-1",
            "__interrupt__": [
                SimpleNamespace(value={"kind": "itinerary_confirmation", "draft": "草案"})
            ],
            "messages": [],
        }
    )

    assert response["status"] == "awaiting_human"
    assert response["requires_human_approval"] is True
    assert response["approval_payload"]["draft"] == "草案"
