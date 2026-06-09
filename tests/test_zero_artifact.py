"""M3 AC#4 (A3): all workers fail -> failed report, every dimension gapped, CLI exits non-zero."""

import asyncio
from collections.abc import Callable

from starlette.applications import Starlette

from crypto_deep_research.__main__ import exit_code
from crypto_deep_research.contracts.memory import LongTermMemory
from crypto_deep_research.orchestrator.app import run_orchestrator
from crypto_deep_research.workers.market.service import build_market_app
from crypto_deep_research.workers.onchain.service import build_onchain_app
from crypto_deep_research.workers.orderbook.service import build_orderbook_app


def test_all_failed_workers_yield_failed_report(
    serve: Callable[[Starlette], str],
    dead_mcp_url: str,
    longterm: Callable[..., LongTermMemory],
) -> None:
    worker_urls = [
        serve(build_market_app(dead_mcp_url, "http://stub")),
        serve(build_orderbook_app(dead_mcp_url, "http://stub")),
        serve(build_onchain_app(dead_mcp_url, "http://stub")),
    ]
    report = asyncio.run(
        run_orchestrator("BTC", "zero", worker_urls, longterm(watchlist=["BTC"]), 5.0)
    )

    assert report.status == "failed"
    assert report.dimensions_ok == []
    gapped = {gap.dimension for gap in report.dimensions_unavailable}
    assert gapped == {"market", "orderbook", "onchain"}
    assert exit_code(report) == 1  # zero coverage -> CLI exits non-zero (A3)
