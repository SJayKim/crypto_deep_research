"""Market worker: a LangGraph ``data -> work`` agent over the MCP boundary.

``data`` pulls OHLCV from the MCP server; ``work`` reasons over the close series in the
worker's own LLM context and distills a bounded ``WorkerArtifact`` (A2). An unreachable
MCP server short-circuits to ``status="failed"`` without touching the LLM (A3). Built on
the shared ``workers/base`` harness (C6).
"""

import asyncio
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from crypto_deep_research.contracts.artifact import WorkerArtifact
from crypto_deep_research.contracts.mcp_tools import OHLCV
from crypto_deep_research.workers.base import llm_distill, run_worker, seed_context


async def _fetch_ohlcv(mcp_url: str, symbol: str) -> OHLCV:
    async with streamable_http_client(mcp_url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("get_ohlcv", {"symbol": symbol})
            return OHLCV.model_validate(result.structuredContent)


def _fetch(mcp_url: str, symbol: str) -> OHLCV:
    return asyncio.run(_fetch_ohlcv(mcp_url, symbol))


def _work(symbol: str, ohlcv: OHLCV, episodic_seed: dict[str, str] | None = None) -> WorkerArtifact:
    series = ", ".join(f"{b.ts}:{b.close}" for b in ohlcv.bars)
    prompt = (
        f"You are a crypto market analyst. Analyze {symbol} from these daily close prices "
        f"(unix_ts:close): {series}. Discuss trend, momentum, and notable levels. Be concise "
        "and specific with numbers."
        f"{seed_context(episodic_seed)}"
    )
    return llm_distill("market", prompt)


def analyze_market(
    symbol: str,
    mcp_url: str,
    episodic_seed: dict[str, str] | None = None,
    checkpointer: Any = None,
) -> WorkerArtifact:
    return run_worker(
        "market",
        _fetch,
        _work,
        symbol,
        mcp_url,
        checkpointer=checkpointer,
        episodic_seed=episodic_seed,
    )
