"""M3 AC#3 (TENSION-C): one worker fails -> the report is partial with the gap surfaced."""

import asyncio
from collections.abc import Callable

from starlette.applications import Starlette

from crypto_deep_research.__main__ import exit_code, render_report
from crypto_deep_research.contracts.memory import LongTermMemory
from crypto_deep_research.orchestrator.app import run_orchestrator
from crypto_deep_research.workers.market.service import build_market_app
from crypto_deep_research.workers.onchain.service import build_onchain_app
from crypto_deep_research.workers.orderbook.service import build_orderbook_app


def test_one_failed_worker_yields_partial_report(
    serve: Callable[[Starlette], str],
    mcp_url: str,
    dead_mcp_url: str,
    longterm: Callable[..., LongTermMemory],
) -> None:
    worker_urls = [
        serve(build_market_app(dead_mcp_url, "http://stub")),  # MCP down -> failed (gap)
        serve(build_orderbook_app(mcp_url, "http://stub")),  # ok (deterministic)
        serve(build_onchain_app(mcp_url, "http://stub")),  # ok (deterministic)
    ]
    report = asyncio.run(
        run_orchestrator("BTC", "partial", worker_urls, longterm(watchlist=["BTC"]), 5.0)
    )

    assert report.status == "partial"
    assert set(report.dimensions_ok) == {"orderbook", "onchain"}
    gaps = {gap.dimension: gap.reason for gap in report.dimensions_unavailable}
    assert "market" in gaps
    assert gaps["market"]  # a non-empty reason, never a silent gap (A3)

    rendered = render_report(report)
    assert "market" in rendered
    assert exit_code(report) == 0  # partial is still a result, not a failure
