"""Orderbook worker: a deterministic ``data -> work`` agent over the MCP boundary.

``data`` pulls top-of-book bids/asks from the MCP server; ``work`` computes spread, mid,
and depth imbalance directly into a bounded ``WorkerArtifact`` (A2) -- order-book signal
is deterministic, so no LLM (DESIGN). MCP down -> ``status="failed"`` (A3). Built on the
shared ``workers/base`` harness (C6).
"""

import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from crypto_deep_research.contracts.artifact import Evidence, WorkerArtifact
from crypto_deep_research.contracts.mcp_tools import Orderbook
from crypto_deep_research.workers.base import run_worker


async def _fetch_orderbook(mcp_url: str, symbol: str) -> Orderbook:
    async with streamable_http_client(mcp_url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("get_orderbook", {"symbol": symbol})
            return Orderbook.model_validate(result.structuredContent)


def _fetch(mcp_url: str, symbol: str) -> Orderbook:
    return asyncio.run(_fetch_orderbook(mcp_url, symbol))


def _work(symbol: str, ob: Orderbook) -> WorkerArtifact:
    best_bid = max(level.price for level in ob.bids)
    best_ask = min(level.price for level in ob.asks)
    spread = best_ask - best_bid
    mid = (best_bid + best_ask) / 2
    bid_depth = sum(level.size for level in ob.bids)
    ask_depth = sum(level.size for level in ob.asks)
    imbalance = (bid_depth - ask_depth) / (bid_depth + ask_depth)
    bps = spread / mid * 1e4
    return WorkerArtifact(
        dimension="orderbook",
        status="ok",
        headline=f"{symbol} spread {spread:.1f} ({bps:.1f} bps), imbalance {imbalance:+.2f}",
        key_points=[
            f"best bid {best_bid}, best ask {best_ask}",
            f"bid depth {bid_depth:.1f}, ask depth {ask_depth:.1f}",
            f"{'bid' if imbalance > 0 else 'ask'}-heavy book",
        ],
        evidence=[
            Evidence(metric="spread", value=spread),
            Evidence(metric="mid", value=mid),
            Evidence(metric="depth_imbalance", value=round(imbalance, 4)),
        ],
    )


def analyze_orderbook(symbol: str, mcp_url: str) -> WorkerArtifact:
    return run_worker("orderbook", _fetch, _work, symbol, mcp_url)
