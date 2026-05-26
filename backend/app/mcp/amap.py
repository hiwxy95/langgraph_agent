from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Iterable

from langchain_core.tools import BaseTool, StructuredTool

from app.core.config import Settings, get_settings


CITY_CENTER_LOCATIONS = {
    "广州": "113.264385,23.129112",
    "深圳": "114.057868,22.543099",
    "汕头": "116.681972,23.354091",
    "珠海": "113.576726,22.270715",
    "佛山": "113.121416,23.021548",
    "东莞": "113.751765,23.020536",
    "惠州": "114.416196,23.111847",
    "潮州": "116.622603,23.65695",
    "揭阳": "116.372831,23.549993",
    "梅州": "116.122046,24.288832",
    "中山": "113.3926,22.51595",
    "江门": "113.081901,22.578738",
    "湛江": "110.359377,21.270708",
    "茂名": "110.925456,21.662999",
    "肇庆": "112.465245,23.047747",
    "清远": "113.056098,23.682064",
    "韶关": "113.597522,24.810403",
    "阳江": "111.982232,21.857958",
    "云浮": "112.044439,22.929801",
    "河源": "114.700447,23.743538",
    "汕尾": "115.375557,22.786211",
}


@dataclass(frozen=True)
class AmapToolResult:
    tool_name: str
    content: Any


class AmapMCPClient:
    """Business-level wrapper over Amap's MCP tools."""

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
        origin_location = await self._resolve_location(origin, None)
        destination_location = await self._resolve_location(destination, city)
        tool = await self._select_tool(
            explicit_name=self.settings.amap_route_tool,
            preferred_keywords=(
                mode,
                "direction",
                "route",
                "path",
                "navigation",
                "driving",
                "walking",
                "transit",
                "路线",
                "路径",
                "驾车",
                "步行",
                "公交",
            ),
        )
        payload = {"origin": origin_location, "destination": destination_location}
        if mode in {"walking", "bicycling", "driving"}:
            payload["strategy"] = "0"
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
            preferred_keywords=("text", "poi", "place", "search", "关键字", "搜索"),
        )
        return AmapToolResult(
            tool.name, await self._invoke_tool(tool, {"keywords": keyword or "酒店", "city": city})
        )

    async def search_attractions(
        self,
        city: str,
        keyword: str = "景点",
        location: str | None = None,
        radius: int = 10000,
    ) -> AmapToolResult:
        tool = await self._select_tool(
            explicit_name=self.settings.amap_attraction_tool,
            preferred_keywords=("text", "poi", "place", "search", "关键字", "搜索"),
        )
        return AmapToolResult(
            tool.name, await self._invoke_tool(tool, {"keywords": keyword or "景点", "city": city})
        )

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
                description="查询城市内酒店 POI 信息，参数 city、keyword。",
            ),
            StructuredTool.from_function(
                coroutine=search_attractions_tool,
                name="search_attractions",
                description="查询城市内景点 POI 信息，参数 city、keyword。",
            ),
        ]

    async def _resolve_location(self, address_or_location: str, city: str | None) -> str:
        normalized = address_or_location.strip()
        if _looks_like_location(normalized):
            return normalized
        if normalized in CITY_CENTER_LOCATIONS:
            return CITY_CENTER_LOCATIONS[normalized]

        geo_tool = await self._select_tool(
            explicit_name=None,
            preferred_keywords=("geo", "geocode", "地理编码", "地址"),
        )
        result = await self._invoke_tool(geo_tool, {"address": normalized})
        location = _extract_location(result)
        if not location and city:
            result = await self._invoke_tool(geo_tool, {"address": f"{city}{normalized}"})
            location = _extract_location(result)

        if not location:
            preview = normalize_tool_content(result)[:500]
            raise RuntimeError(f"无法把地址解析为经纬度：{normalized}。高德返回：{preview}")
        return location

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
            make_tool("offline_geo", "Offline geocode placeholder."),
            make_tool("offline_route", "Offline route placeholder."),
            make_tool("offline_text_search", "Offline text search placeholder."),
        ]


def normalize_tool_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, indent=2, default=str)


def _looks_like_location(value: str) -> bool:
    parts = value.split(",")
    if len(parts) != 2:
        return False
    try:
        longitude = float(parts[0])
        latitude = float(parts[1])
    except ValueError:
        return False
    return -180 <= longitude <= 180 and -90 <= latitude <= 90


def _extract_location(value: Any) -> str | None:
    if isinstance(value, str):
        try:
            return _extract_location(json.loads(value))
        except json.JSONDecodeError:
            return value if _looks_like_location(value) else None
    if isinstance(value, list):
        for item in value:
            location = _extract_location(item)
            if location:
                return location
    if isinstance(value, dict):
        for key in ("location", "lnglat", "lng_lat", "center"):
            direct = value.get(key)
            if isinstance(direct, str) and _looks_like_location(direct):
                return direct
        longitude = value.get("lng") or value.get("longitude")
        latitude = value.get("lat") or value.get("latitude")
        if longitude is not None and latitude is not None:
            candidate = f"{longitude},{latitude}"
            if _looks_like_location(candidate):
                return candidate
        for key in ("geocodes", "pois", "data", "result", "results", "content"):
            if key in value:
                location = _extract_location(value[key])
                if location:
                    return location
    return None
