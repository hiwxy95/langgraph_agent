from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Iterable

from langchain_core.tools import BaseTool, StructuredTool
from app.core.config import Settings, get_settings


@dataclass(frozen=True)
class AmapToolResult:
    tool_name: str
    content: Any


class AmapMCPClient:
    """Business-level wrapper over Amap's MCP tools.

    The public Amap MCP service may evolve tool names over time. The wrapper keeps
    the app API stable and supports explicit tool-name overrides through env vars.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._tools: list[BaseTool] | None = None

    async def get_tools(self) -> list[BaseTool]:
        if self._tools is not None:
            return self._tools
        if not self.settings.amap_maps_api_key:
            self._tools = self._offline_tools()
            return self._tools

        from langchain_mcp_adapters.client import MultiServerMCPClient

        client = MultiServerMCPClient(
            {
                "amap": {
                    "url": self.settings.resolved_amap_mcp_url,
                    "transport": "streamable_http",
                }
            }
        )
        self._tools = await client.get_tools()
        return self._tools

    async def plan_route(
        self,
        origin: str,
        destination: str,
        city: str | None = None,
        mode: str = "driving",
    ) -> AmapToolResult:
        tool = await self._select_tool(
            explicit_name=self.settings.amap_route_tool,
            preferred_keywords=(mode, "route", "direction", "path", "路线", "路径", "驾车", "步行", "公交"),
        )
        payload = {
            "origin": origin,
            "destination": destination,
            "city": city,
            "mode": mode,
            "keywords": f"{origin} 到 {destination}",
        }
        return AmapToolResult(tool.name, await self._invoke_tool(tool, payload))

    async def search_hotels(
        self,
        city: str,
        keyword: str = "酒店",
        location: str | None = None,
        radius: int = 5000,
    ) -> AmapToolResult:
        tool = await self._select_tool(
            explicit_name=self.settings.amap_hotel_tool,
            preferred_keywords=("hotel", "poi", "place", "search", "酒店", "住宿", "地点", "搜索"),
        )
        payload = {
            "city": city,
            "keywords": keyword or "酒店",
            "types": "100000",
            "location": location,
            "radius": radius,
        }
        return AmapToolResult(tool.name, await self._invoke_tool(tool, payload))

    async def search_attractions(
        self,
        city: str,
        keyword: str = "景点",
        location: str | None = None,
        radius: int = 10000,
    ) -> AmapToolResult:
        tool = await self._select_tool(
            explicit_name=self.settings.amap_attraction_tool,
            preferred_keywords=("scenic", "attraction", "poi", "place", "search", "景点", "风景", "搜索"),
        )
        payload = {
            "city": city,
            "keywords": keyword or "景点",
            "types": "110000",
            "location": location,
            "radius": radius,
        }
        return AmapToolResult(tool.name, await self._invoke_tool(tool, payload))

    async def as_langchain_tools(self) -> list[BaseTool]:
        async def plan_route_tool(
            origin: str,
            destination: str,
            city: str | None = None,
            mode: str = "driving",
        ) -> dict[str, Any]:
            result = await self.plan_route(origin, destination, city, mode)
            return {"tool_name": result.tool_name, "content": result.content}

        async def search_hotels_tool(
            city: str,
            keyword: str = "酒店",
            location: str | None = None,
            radius: int = 5000,
        ) -> dict[str, Any]:
            result = await self.search_hotels(city, keyword, location, radius)
            return {"tool_name": result.tool_name, "content": result.content}

        async def search_attractions_tool(
            city: str,
            keyword: str = "景点",
            location: str | None = None,
            radius: int = 10000,
        ) -> dict[str, Any]:
            result = await self.search_attractions(city, keyword, location, radius)
            return {"tool_name": result.tool_name, "content": result.content}

        return [
            StructuredTool.from_function(
                coroutine=plan_route_tool,
                name="plan_route",
                description="规划两个地点之间的路线，参数 origin、destination、city、mode。",
            ),
            StructuredTool.from_function(
                coroutine=search_hotels_tool,
                name="search_hotels",
                description="查询城市内酒店 POI 信息，参数 city、keyword、location、radius。",
            ),
            StructuredTool.from_function(
                coroutine=search_attractions_tool,
                name="search_attractions",
                description="查询城市内景点 POI 信息，参数 city、keyword、location、radius。",
            ),
        ]

    async def _select_tool(
        self, explicit_name: str | None, preferred_keywords: Iterable[str]
    ) -> BaseTool:
        tools = await self.get_tools()
        if explicit_name:
            for tool in tools:
                if tool.name == explicit_name:
                    return tool
            raise RuntimeError(f"Amap MCP tool '{explicit_name}' was not found.")

        scored = sorted(
            tools,
            key=lambda tool: self._score_tool(tool, preferred_keywords),
            reverse=True,
        )
        if not scored or self._score_tool(scored[0], preferred_keywords) <= 0:
            names = ", ".join(tool.name for tool in tools)
            raise RuntimeError(f"No matching Amap MCP tool found. Available tools: {names}")
        return scored[0]

    @staticmethod
    def _score_tool(tool: BaseTool, keywords: Iterable[str]) -> int:
        haystack = f"{tool.name} {tool.description or ''}".lower()
        return sum(1 for keyword in keywords if keyword.lower() in haystack)

    @staticmethod
    async def _invoke_tool(tool: BaseTool, payload: dict[str, Any]) -> Any:
        clean_payload = {key: value for key, value in payload.items() if value is not None}
        try:
            return await tool.ainvoke(clean_payload)
        except TypeError:
            return await tool.ainvoke(json.dumps(clean_payload, ensure_ascii=False))

    def _offline_tools(self) -> list[BaseTool]:
        async def missing_key_tool(**kwargs: Any) -> dict[str, Any]:
            return {
                "error": "AMAP_MAPS_API_KEY is not configured.",
                "received": kwargs,
            }

        def make_tool(name: str, description: str) -> BaseTool:
            return StructuredTool.from_function(
                coroutine=missing_key_tool,
                name=name,
                description=description,
            )

        return [
            make_tool("offline_route", "Offline route placeholder."),
            make_tool("offline_hotel_search", "Offline hotel search placeholder."),
            make_tool("offline_attraction_search", "Offline attraction search placeholder."),
        ]


def normalize_tool_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, indent=2, default=str)
