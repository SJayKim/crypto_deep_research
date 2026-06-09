"""Sentiment worker: a LangGraph ``data -> work`` LLM agent over the MCP boundary.

``data`` pulls recent news headlines (each with a per-item sentiment) from the MCP
server; ``work`` reasons over net tone and source credibility in the worker's own LLM
context and distills a bounded ``WorkerArtifact`` (A2). MCP down -> ``status="failed"``
(A3). Built on the shared ``workers/base`` harness (C6).
"""

import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from crypto_deep_research.contracts.artifact import WorkerArtifact
from crypto_deep_research.contracts.mcp_tools import News
from crypto_deep_research.workers.base import llm_distill, run_worker


async def _fetch_news(mcp_url: str, symbol: str) -> News:
    async with streamable_http_client(mcp_url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("get_news", {"symbol": symbol})
            return News.model_validate(result.structuredContent)


def _fetch(mcp_url: str, symbol: str) -> News:
    return asyncio.run(_fetch_news(mcp_url, symbol))


def _work(symbol: str, news: News) -> WorkerArtifact:
    items = "; ".join(f"{i.title} [{i.source}, {i.sentiment:+.2f}]" for i in news.items)
    prompt = (
        f"You are a crypto sentiment analyst. Assess market sentiment for {symbol} from these "
        f"recent headlines (title [source, score]): {items}. Weigh source credibility and net "
        "tone. Be concise and specific."
    )
    return llm_distill("sentiment", prompt)


def analyze_sentiment(symbol: str, mcp_url: str) -> WorkerArtifact:
    return run_worker("sentiment", _fetch, _work, symbol, mcp_url)
