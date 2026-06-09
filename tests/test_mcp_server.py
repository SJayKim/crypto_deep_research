"""M1 MCP server: all 4 tools answer over real streamable HTTP, stateless (T7b, AC#1)."""

import asyncio
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import BaseModel

from crypto_deep_research.contracts.mcp_tools import OHLCV, News, OnchainMetrics, Orderbook


async def _call(mcp_url: str, name: str, args: dict[str, Any]) -> Any:
    async with streamable_http_client(mcp_url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool(name, args)


async def _list(mcp_url: str) -> Any:
    async with streamable_http_client(mcp_url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await session.list_tools()


def test_lists_all_four_tools(mcp_url: str) -> None:
    tools = asyncio.run(_list(mcp_url))
    assert {t.name for t in tools.tools} == {
        "get_ohlcv",
        "get_orderbook",
        "get_news",
        "get_onchain",
    }


def test_each_tool_returns_valid_schema(mcp_url: str) -> None:
    cases: list[tuple[str, type[BaseModel]]] = [
        ("get_ohlcv", OHLCV),
        ("get_orderbook", Orderbook),
        ("get_news", News),
        ("get_onchain", OnchainMetrics),
    ]
    for name, model in cases:
        result = asyncio.run(_call(mcp_url, name, {"symbol": "BTC"}))
        model.model_validate(result.structuredContent)


def test_concurrent_calls_return_identical_data(mcp_url: str) -> None:
    async def _four() -> list[Any]:
        return await asyncio.gather(
            *[_call(mcp_url, "get_ohlcv", {"symbol": "BTC"}) for _ in range(4)]
        )

    payloads = [r.structuredContent for r in asyncio.run(_four())]
    assert all(p == payloads[0] for p in payloads)
