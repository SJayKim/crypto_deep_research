"""M3 AC#1 (parallel fan-out) + AC#7 (data-driven registry): asyncio.gather over A2A.

[한글 설명] ARCHITECTURE-MAP §7의 "병렬 fan-out"에 해당. 5대 개념 중 Orchestrator-Worker의
디스패치 절반. 결정코드 P9: fan-out은 반드시 asyncio.gather여야 한다(LangGraph Send 금지 —
Send는 오케스트레이터 프로세스 안에서만 돌아 A2A 경계를 못 넘고, 그러면 Approach B가 A로
조용히 붕괴한다). 검증 두 개: (1) AC#7 — Agent Card 발견으로 차원→워커 레지스트리가 데이터
주도로 구성됨(워커 추가 시 orchestrator 코드 수정 불필요), (2) AC#1 — 병렬이라 총 지연이 합이
아니라 가장 느린 워커 수준이라는 것.
"""

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


# 4개 워커를 띄우면 discover가 각 Agent Card를 읽어 {차원: URL} 레지스트리를 정확히 만드는지.
# = 워커 추가가 환경/카드 주도이고 orchestrator 코드를 안 건드린다는 데이터 주도 배선(AC#7).
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


# 0.5초씩 자는 워커 2개를 동시에 호출했을 때 총 시간이 ~1초가 아니라 ~0.5초인지.
# = fan-out이 진짜 병렬(asyncio.gather)이라는 증거. 순차였다면 합만큼 걸린다(P9, AC#1).
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
