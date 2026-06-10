"""M3 AC#5 (A3): a worker exceeding the timeout becomes a gap; the gather still returns."""

import asyncio
from collections.abc import AsyncIterator, Callable

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route

from crypto_deep_research.contracts.a2a import JsonRpcResponse
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


def test_trickle_byte_worker_hits_wall_clock_deadline(
    serve: Callable[[Starlette], str],
) -> None:
    """O1: a worker that dribbles bytes slower than the deadline -- but never idle long enough
    to trip httpx's read timeout -- must still become a ``timeout`` gap. The bound is the
    ``asyncio.wait_for`` wall-clock deadline, not httpx's per-op timeouts (which this worker
    would slip past, returning ok after the full trickle)."""
    artifact = WorkerArtifact(
        dimension="market", status="ok", headline="trickle", key_points=["done"]
    )
    body = JsonRpcResponse(id="tb", result=artifact).model_dump_json().encode()

    async def analyze(request: Request) -> Response:
        async def trickle() -> AsyncIterator[bytes]:
            for i in range(0, len(body), 4):
                yield body[i : i + 4]
                await asyncio.sleep(0.1)  # < the 0.3s deadline -> httpx read never times out

        return StreamingResponse(trickle(), media_type="application/json")

    app = Starlette(routes=[Route("/", analyze, methods=["POST"])])
    results = asyncio.run(fan_out({"market": serve(app)}, "BTC", "tb", timeout_s=0.3))

    gap = results[0]
    assert isinstance(gap, DimensionGap)
    assert gap.reason == "timeout"
