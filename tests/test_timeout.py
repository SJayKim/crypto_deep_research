"""M3 AC#5 (A3): a worker exceeding the timeout becomes a gap; the gather still returns.

[한글 설명] ARCHITECTURE-MAP §7의 "타임아웃"(A3 + TENSION-C)에 해당. 결정코드 A3: 워커마다
30s 타임아웃(env 조정 가능)을 asyncio.gather로 건다. 핵심 보장: 느린 워커 하나가 전체 런을
인질로 잡지 못한다 — 타임아웃을 넘긴 차원은 timeout gap이 되고, 나머지 워커 결과는 정상 수집된다.
또 O1: 바이트를 찔끔찔끔 흘려 httpx의 read timeout은 피하는 악성 워커도 wall-clock 데드라인
(asyncio.wait_for)으로 반드시 잘려야 한다는 미묘한 경계까지 검증한다.
"""

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


# 한 워커는 2초 자고(0.3초 타임아웃 초과) 다른 워커는 즉시 응답. 느린 쪽은 timeout gap,
# 빠른 쪽은 정상 ok로 같이 돌아오는지 = 느린 워커가 전체를 막지 않는다는 A3 핵심(AC#5).
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


# O1: 바이트를 0.1초 간격으로 찔끔 흘려 httpx read timeout은 안 걸리지만 전체는 데드라인을
# 넘기는 워커. 이래도 timeout gap이 되는지 = 진짜 차단선은 wall-clock(asyncio.wait_for)이라는 검증.
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
