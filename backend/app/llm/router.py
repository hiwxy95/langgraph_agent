from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI

from app.core.config import ModelProvider, Settings, get_settings

TaskType = Literal[
    "chat",
    "single_lookup",
    "route_planning",
    "itinerary_planning",
    "react_reasoning",
    "summary",
]


@dataclass(frozen=True)
class RoutedLLMResult:
    content: str
    provider: Literal["deepseek", "qwen"]
    model: str
    fallback_from: str | None = None


class LLMRouter:
    """Quality-first router over DeepSeek and Qwen OpenAI-compatible APIs."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._clients: dict[str, ChatOpenAI] = {}

    def select_provider(
        self,
        task_type: TaskType = "chat",
        requested_provider: ModelProvider = "auto",
        hints: dict[str, Any] | None = None,
    ) -> Literal["deepseek", "qwen"]:
        if requested_provider in ("deepseek", "qwen"):
            return requested_provider

        hints = hints or {}
        if hints.get("requires_reasoning") or hints.get("multi_step"):
            return "deepseek"

        if task_type in {"route_planning", "itinerary_planning", "react_reasoning"}:
            return "deepseek"
        return "qwen"

    def get_client(self, provider: Literal["deepseek", "qwen"]) -> ChatOpenAI:
        if provider in self._clients:
            return self._clients[provider]

        if provider == "deepseek":
            if not self.settings.deepseek_api_key:
                raise RuntimeError("DEEPSEEK_API_KEY is required for DeepSeek calls.")
            client = ChatOpenAI(
                api_key=self.settings.deepseek_api_key,
                base_url=self.settings.deepseek_base_url,
                model=self.settings.deepseek_model,
                timeout=self.settings.request_timeout_seconds,
            )
        else:
            if not self.settings.dashscope_api_key:
                raise RuntimeError("DASHSCOPE_API_KEY is required for Qwen calls.")
            client = ChatOpenAI(
                api_key=self.settings.dashscope_api_key,
                base_url=self.settings.dashscope_base_url,
                model=self.settings.qwen_model,
                timeout=self.settings.request_timeout_seconds,
            )

        self._clients[provider] = client
        return client

    async def invoke(
        self,
        messages: list[BaseMessage],
        task_type: TaskType = "chat",
        hints: dict[str, Any] | None = None,
        model_provider: ModelProvider = "auto",
    ) -> RoutedLLMResult:
        provider = self.select_provider(task_type, model_provider, hints)
        fallback = "qwen" if provider == "deepseek" else "deepseek"

        try:
            response = await self.get_client(provider).ainvoke(messages)
            return RoutedLLMResult(
                content=str(response.content),
                provider=provider,
                model=self._model_name(provider),
            )
        except Exception:
            response = await self.get_client(fallback).ainvoke(messages)
            return RoutedLLMResult(
                content=str(response.content),
                provider=fallback,
                model=self._model_name(fallback),
                fallback_from=provider,
            )

    def chat_model(
        self,
        task_type: TaskType = "chat",
        model_provider: ModelProvider = "auto",
        hints: dict[str, Any] | None = None,
    ) -> ChatOpenAI:
        provider = self.select_provider(task_type, model_provider, hints)
        return self.get_client(provider)

    def _model_name(self, provider: str) -> str:
        if provider == "deepseek":
            return self.settings.deepseek_model
        return self.settings.qwen_model
