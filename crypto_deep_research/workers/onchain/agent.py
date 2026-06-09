"""Onchain worker: a deterministic ``data -> work`` agent over the MCP boundary.

``data`` pulls on-chain metrics from the MCP server; ``work`` reads active addresses, tx
volume, and exchange netflow directly into a bounded ``WorkerArtifact`` (A2) -- the
on-chain signal is deterministic, so no LLM (builder's call at M3, per the epic). MCP
down -> ``status="failed"`` (A3). Built on the shared ``workers/base`` harness (C6).
"""

import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from crypto_deep_research.contracts.artifact import Evidence, WorkerArtifact
from crypto_deep_research.contracts.mcp_tools import OnchainMetrics
from crypto_deep_research.workers.base import run_worker


async def _fetch_onchain(mcp_url: str, symbol: str) -> OnchainMetrics:
    async with streamable_http_client(mcp_url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("get_onchain", {"symbol": symbol})
            return OnchainMetrics.model_validate(result.structuredContent)


def _fetch(mcp_url: str, symbol: str) -> OnchainMetrics:
    return asyncio.run(_fetch_onchain(mcp_url, symbol))


def _work(symbol: str, m: OnchainMetrics) -> WorkerArtifact:
    flow = "outflow (accumulation)" if m.exchange_netflow < 0 else "inflow (distribution)"
    return WorkerArtifact(
        dimension="onchain",
        status="ok",
        headline=f"{symbol}: {m.active_addresses} active addresses, net exchange {flow}",
        key_points=[
            f"active addresses {m.active_addresses}",
            f"tx volume {m.tx_volume}",
            f"exchange netflow {m.exchange_netflow}",
        ],
        evidence=[
            Evidence(metric="active_addresses", value=m.active_addresses),
            Evidence(metric="tx_volume", value=m.tx_volume),
            Evidence(metric="exchange_netflow", value=m.exchange_netflow),
        ],
    )


def analyze_onchain(symbol: str, mcp_url: str) -> WorkerArtifact:
    return run_worker("onchain", _fetch, _work, symbol, mcp_url)
