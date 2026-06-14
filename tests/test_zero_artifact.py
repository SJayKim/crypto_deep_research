"""M3 AC#4 (A3): all workers fail -> failed report, every dimension gapped, CLI exits non-zero.

[한글 설명] ARCHITECTURE-MAP §7의 "전체 실패"(A3)에 해당. test_partial이 부분 실패를 봤다면
여기선 zero-artifact 경계: 모든 워커가 실패하면 status="failed", 모든 차원이 gap, 그리고 CLI는
non-zero(1)로 종료한다. "결과가 하나도 없으면 가짜 리포트를 만들지 말고 명확히 실패로 알린다"는
A3의 zero 케이스. exit code 1은 자동화/스크립트가 실패를 감지할 수 있게 하는 핵심.
"""

import asyncio
from collections.abc import Callable

from starlette.applications import Starlette

from crypto_deep_research.__main__ import exit_code
from crypto_deep_research.contracts.memory import LongTermMemory
from crypto_deep_research.orchestrator.app import run_orchestrator
from crypto_deep_research.workers.market.service import build_market_app
from crypto_deep_research.workers.onchain.service import build_onchain_app
from crypto_deep_research.workers.orderbook.service import build_orderbook_app


# 워커 전부 MCP 죽음으로 실패 → status="failed", dimensions_ok 비고, 모든 차원이 gap,
# exit code 1(non-zero)인지. 커버리지 0일 때 가짜 성공 리포트를 내지 않는다는 A3 zero 케이스(AC#4).
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
