from functools import lru_cache
from typing import Literal

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


ModelProvider = Literal["auto", "deepseek", "qwen"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Travel AI Agent"
    api_prefix: str = "/api"
    frontend_origin: str = "http://localhost:5173"

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/travel_agent"
    )
    checkpoint_database_url: str | None = None

    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    dashscope_api_key: str | None = None
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_model: str = "qwen-plus"

    amap_maps_api_key: str | None = None
    amap_mcp_url: str = "https://mcp.amap.com/mcp?key={AMAP_MAPS_API_KEY}"
    amap_route_tool: str | None = None
    amap_hotel_tool: str | None = None
    amap_attraction_tool: str | None = None

    request_timeout_seconds: float = 45.0

    @computed_field  # type: ignore[misc]
    @property
    def checkpoint_url(self) -> str:
        if self.checkpoint_database_url:
            return self.checkpoint_database_url
        if self.database_url.startswith("postgresql+asyncpg://"):
            return self.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        return self.database_url

    @computed_field  # type: ignore[misc]
    @property
    def resolved_amap_mcp_url(self) -> str:
        key = self.amap_maps_api_key or ""
        return self.amap_mcp_url.replace("{AMAP_MAPS_API_KEY}", key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
