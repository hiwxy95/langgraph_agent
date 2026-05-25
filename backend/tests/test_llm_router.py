from app.core.config import Settings
from app.llm.router import LLMRouter


def make_router() -> LLMRouter:
    return LLMRouter(
        Settings(
            deepseek_api_key="deepseek-key",
            dashscope_api_key="qwen-key",
            database_url="postgresql+asyncpg://user:pass@localhost/db",
        )
    )


def test_quality_first_routes_complex_tasks_to_deepseek() -> None:
    router = make_router()

    assert router.select_provider("itinerary_planning") == "deepseek"
    assert router.select_provider("react_reasoning") == "deepseek"
    assert router.select_provider("route_planning") == "deepseek"


def test_quality_first_routes_simple_tasks_to_qwen() -> None:
    router = make_router()

    assert router.select_provider("chat") == "qwen"
    assert router.select_provider("single_lookup") == "qwen"
    assert router.select_provider("summary") == "qwen"


def test_requested_provider_overrides_auto_route() -> None:
    router = make_router()

    assert router.select_provider("chat", requested_provider="deepseek") == "deepseek"
    assert router.select_provider("itinerary_planning", requested_provider="qwen") == "qwen"


def test_reasoning_hints_route_to_deepseek() -> None:
    router = make_router()

    assert router.select_provider("chat", hints={"requires_reasoning": True}) == "deepseek"
    assert router.select_provider("single_lookup", hints={"multi_step": True}) == "deepseek"
