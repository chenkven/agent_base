"""Verify the bundled read-only MCP server without using an LLM API key."""

import argparse
import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def probe(url: str) -> None:
    async with streamable_http_client(url) as (reader, writer, _):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [tool.name for tool in tools.tools]
            assert {"current_time", "add_numbers"} <= set(names), names
            result = await session.call_tool("add_numbers", {"a": 2, "b": 3})
            assert not result.isError, result
            assert "5" in str(result.content), result
            print("MCP connected; tools:", ", ".join(names), "; add_numbers(2,3)=5")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000/internal/mcp")
    asyncio.run(probe(parser.parse_args().url))
