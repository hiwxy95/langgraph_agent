from typing import Any
import asyncio

from langchain_core.tools import StructuredTool

from app.core.config import Settings
from app.mcp.amap import AmapMCPClient


async def fake_tool(
    origin: str | None = None,
    destination: str | None = None,
    city: str | None = None,
    mode: str | None = None,
    keywords: str | None = None,
    types: str | None = None,
    location: str | None = None,
    radius: int | None = None,
) -> dict[str, Any]:
    return {
        "origin": origin,
        "destination": destination,
        "city": city,
        "mode": mode,
        "keywords": keywords,
        "types": types,
        "location": location,
        "radius": radius,
    }


def make_tool(name: str, description: str) -> StructuredTool:
    return StructuredTool.from_function(
        coroutine=fake_tool,
        name=name,
        description=description,
    )


def test_search_hotels_uses_hotel_tool_and_poi_type() -> None:
    async def run() -> None:
        client = AmapMCPClient(Settings(amap_maps_api_key="key"))
        client._tools = [make_tool("maps_text_search", "poi search 酒店 景点")]

        result = await client.search_hotels(city="广州", keyword="天河酒店")

        assert result.tool_name == "maps_text_search"
        assert result.content["city"] == "广州"
        assert result.content["keywords"] == "天河酒店"
        assert result.content["types"] == "100000"

    asyncio.run(run())


def test_search_attractions_uses_attraction_type() -> None:
    async def run() -> None:
        client = AmapMCPClient(Settings(amap_maps_api_key="key"))
        client._tools = [make_tool("maps_text_search", "poi search 景点")]

        result = await client.search_attractions(city="广州", keyword="博物馆")

        assert result.tool_name == "maps_text_search"
        assert result.content["city"] == "广州"
        assert result.content["keywords"] == "博物馆"
        assert result.content["types"] == "110000"

    asyncio.run(run())


def test_plan_route_can_use_explicit_tool_name() -> None:
    async def run() -> None:
        client = AmapMCPClient(
            Settings(amap_maps_api_key="key", amap_route_tool="route_tool")
        )
        client._tools = [make_tool("route_tool", "route planning")]

        result = await client.plan_route(
            origin="广州塔", destination="陈家祠", mode="driving"
        )

        assert result.tool_name == "route_tool"
        assert result.content["origin"] == "广州塔"
        assert result.content["destination"] == "陈家祠"
        assert result.content["mode"] == "driving"

    asyncio.run(run())
