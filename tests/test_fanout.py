"""M3 AC#1 (parallel fan-out) + AC#7 (data-driven registry): asyncio.gather over A2A."""

import asyncio
import time
from collections.abc import Callable

from starlette.applications import Starlette

from crypto_deep_research.contracts.artifact import Dimension, WorkerArtifact
from crypto_deep_research.orchestrator.dispatch import fan_out
from crypto_deep_research.orchestrator.planner import discover
from crypto_deep_research.workers.market.service import build_market_app
from crypto_deep_research.workers.onchain.service import build_onchain_app
from crypto_deep_research.workers.orderbook.service import build_orderbook_app
from crypto_deep_research.workers.sentiment.service import build_sentiment_app


def test_discover_maps_all_four_dimensions(
    serve: Callable[[Starlette], str], mcp_url: str
) -> None:  # AC#7: adding workers is data-driven, no orchestrator edit
    urls = [
        serve(build_market_app(mcp_url, "http://stub")),
        serve(build_orderbook_app(mcp_url, "http://stub")),
        serve(build_sentiment_app(mcp_url, "http://stub")),
        serve(build_onchain_app(mcp_url, "http://stub")),
    ]
    registry = asyncio.run(discover(urls))
    assert set(registry) == {"market", "orderbook", "sentiment", "onchain"}
    assert registry["market"] == urls[0]
    assert registry["onchain"] == urls[3]


def test_fan_out_runs_in_parallel(
    serve: Callable[[Starlette], str],
    slow_app: Callable[[Dimension, float], Starlette],
) -> None:  # AC#1: total latency ~ slowest worker, not the sum
    delay = 0.5
    plan: dict[Dimension, str] = {
        "market": serve(slow_app("market", delay)),
        "orderbook": serve(slow_app("orderbook", delay)),
    }
    start = time.monotonic()
    results = asyncio.run(fan_out(plan, "BTC", "par", timeout_s=5.0))
    elapsed = time.monotonic() - start
    assert all(isinstance(r, WorkerArtifact) for r in results)
    assert elapsed < 2 * delay  # sequential would be ~2*delay; concurrency keeps it near delay
