import asyncio
import json

from app.mcp.amap import AmapMCPClient


async def main() -> None:
    client = AmapMCPClient()
    tools = await client.get_tools()
    for tool in tools:
        print(f"\n## {tool.name}")
        if tool.description:
            print(tool.description)
        schema = getattr(tool, "args_schema", None)
        if schema and hasattr(schema, "model_json_schema"):
            print(json.dumps(schema.model_json_schema(), ensure_ascii=False, indent=2))
        elif getattr(tool, "args", None):
            print(json.dumps(tool.args, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
