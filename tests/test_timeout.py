"""M3 AC#5 (A3): a worker exceeding the timeout becomes a gap; the gather still returns."""

import asyncio
from collections.abc import Callable

from starlette.applications import Starlette

from crypto_deep_research.contracts.artifact import Dimension, WorkerArtifact
from crypto_deep_research.contracts.report import DimensionGap
from crypto_deep_research.orchestrator.dispatch import fan_out


def test_slow_worker_times_out_while_others_return(
    serve: Callable[[Starlette], str],
    slow_app: Callable[[Dimension, float], Starlette],
) -> None:
    plan: dict[Dimension, str] = {
        "market": serve(slow_app("market", 2.0)),  # exceeds the 0.3s timeout
        "orderbook": serve(slow_app("orderbook", 0.0)),  # responds immediately
    }
    results = asyncio.run(fan_out(plan, "BTC", "to", timeout_s=0.3))
    by_dim = {r.dimension: r for r in results}

    slow = by_dim["market"]
    assert isinstance(slow, DimensionGap)
    assert slow.reason == "timeout"

    fast = by_dim["orderbook"]
    assert isinstance(fast, WorkerArtifact)
    assert fast.status == "ok"
