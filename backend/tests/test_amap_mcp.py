import asyncio
from typing import Any

from langchain_core.tools import StructuredTool

from app.core.config import Settings
from app.mcp.amap import AmapMCPClient


async def fake_tool(
    origin: str | None = None,
    destination: str | None = None,
    city: str | None = None,
    keywords: str | None = None,
    address: str | None = None,
    strategy: str | None = None,
) -> dict[str, Any]:
    if address:
        return {"geocodes": [{"location": "113.321,23.106"}], "address": address}
    return {
        "origin": origin,
        "destination": destination,
        "city": city,
        "keywords": keywords,
        "strategy": strategy,
    }


def make_tool(name: str, description: str) -> StructuredTool:
    return StructuredTool.from_function(
        coroutine=fake_tool,
        name=name,
        description=description,
    )


def test_search_hotels_uses_text_search_without_unsupported_filters() -> None:
    async def run() -> None:
        client = AmapMCPClient(Settings(amap_maps_api_key="key"))
        client._tools = [make_tool("maps_text_search", "poi text search")]

        result = await client.search_hotels(city="广州", keyword="天河酒店")

        assert result.tool_name == "maps_text_search"
        assert result.content["city"] == "广州"
        assert result.content["keywords"] == "天河酒店"
        assert "types" not in result.content

    asyncio.run(run())


def test_search_attractions_uses_text_search_without_unsupported_filters() -> None:
    async def run() -> None:
        client = AmapMCPClient(Settings(amap_maps_api_key="key"))
        client._tools = [make_tool("maps_text_search", "poi text search")]

        result = await client.search_attractions(city="广州", keyword="博物馆")

        assert result.tool_name == "maps_text_search"
        assert result.content["city"] == "广州"
        assert result.content["keywords"] == "博物馆"
        assert "types" not in result.content

    asyncio.run(run())


def test_plan_route_uses_known_city_center_locations() -> None:
    async def run() -> None:
        client = AmapMCPClient(Settings(amap_maps_api_key="key"))
        client._tools = [make_tool("maps_direction_driving", "direction route driving")]

        result = await client.plan_route(
            origin="深圳", destination="汕头", city="汕头", mode="driving"
        )

        assert result.tool_name == "maps_direction_driving"
        assert result.content["origin"] == "114.057868,22.543099"
        assert result.content["destination"] == "116.681972,23.354091"
        assert result.content["strategy"] == "0"

    asyncio.run(run())


def test_plan_route_geocodes_unknown_addresses_before_route_call() -> None:
    async def run() -> None:
        client = AmapMCPClient(Settings(amap_maps_api_key="key"))
        client._tools = [
            make_tool("maps_geo", "geo geocode address"),
            make_tool("maps_direction_driving", "direction route driving"),
        ]

        result = await client.plan_route(
            origin="广州塔", destination="陈家祠", city="广州", mode="driving"
        )

        assert result.tool_name == "maps_direction_driving"
        assert result.content["origin"] == "113.321,23.106"
        assert result.content["destination"] == "113.321,23.106"
        assert result.content["strategy"] == "0"

    asyncio.run(run())
