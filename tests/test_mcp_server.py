"""M1 MCP server: all 4 tools answer over real streamable HTTP, stateless (T7b, AC#1).

[한글 설명] MCP(에이전트↔도구) 경계 검증. ARCHITECTURE-MAP §7의 "MCP 툴"에 해당.
5대 개념 중 'MCP / A2A 분리'의 도구 쪽 절반이다. 코인데이터 서버는 4개 툴
(get_ohlcv/get_orderbook/get_news/get_onchain)을 진짜 streamable HTTP로 노출하고,
stateless·read-only여야 한다(그래서 워커 4개가 동시에 붙어도 안전, premise 1). 여기서는
실제 MCP 클라이언트로 서버에 붙어 툴 목록·스키마·동시호출 일관성을 검증한다.
"""

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


# 서버가 정확히 4개 툴을 노출하는지. 워커별 데이터 도구가 빠짐없이 등록됐다는 계약 확인.
def test_lists_all_four_tools(mcp_url: str) -> None:
    tools = asyncio.run(_list(mcp_url))
    assert {t.name for t in tools.tools} == {
        "get_ohlcv",
        "get_orderbook",
        "get_news",
        "get_onchain",
    }


# 각 툴 응답이 M0 계약 스키마(OHLCV/Orderbook/News/OnchainMetrics)로 검증되는지.
# 도구 경계가 "구조화된 타입"으로 데이터를 돌려준다는 보장(워커 컨텍스트를 작게 유지).
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


# 같은 호출을 4번 동시에 해도 결과가 동일한지. 서버가 stateless라서 워커 4개 동시 접근이
# 안전하다는 premise 1을 검증(상태가 끼면 동시호출 결과가 갈릴 수 있음).
def test_concurrent_calls_return_identical_data(mcp_url: str) -> None:
    async def _four() -> list[Any]:
        return await asyncio.gather(
            *[_call(mcp_url, "get_ohlcv", {"symbol": "BTC"}) for _ in range(4)]
        )

    payloads = [r.structuredContent for r in asyncio.run(_four())]
    assert all(p == payloads[0] for p in payloads)
