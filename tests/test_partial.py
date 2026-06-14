"""M3 AC#3 (TENSION-C): one worker fails -> the report is partial with the gap surfaced.

[한글 설명] ARCHITECTURE-MAP §7의 "부분 실패"(A3 + TENSION-C)에 해당. TENSION-C: 부분 실패를
'조용히' 넘기지 않고 리포트에 명시적으로 드러낸다. 4개 중 1개만 죽어도 전체가 실패하는 게
아니라, 성공 차원은 dimensions_ok에, 실패 차원은 dimensions_unavailable에 '이유'와 함께 표시되고
status="partial"이 된다. 또 부분 성공은 결과이지 실패가 아니므로 CLI exit code는 0(성공)이다.
= "1-of-4 런이 눈에 보이게 partial로 표시"라는 TENSION-C 성공 기준의 직접 검증.
"""

import asyncio
from collections.abc import Callable

from starlette.applications import Starlette

from crypto_deep_research.__main__ import exit_code, render_report
from crypto_deep_research.contracts.memory import LongTermMemory
from crypto_deep_research.orchestrator.app import run_orchestrator
from crypto_deep_research.workers.market.service import build_market_app
from crypto_deep_research.workers.onchain.service import build_onchain_app
from crypto_deep_research.workers.orderbook.service import build_orderbook_app


# market만 MCP 죽어 실패, orderbook/onchain은 성공. 리포트가 status="partial"이고 ok/gap이
# 정확히 갈리며, gap에 빈 reason이 아닌 사유가 있고(조용한 실패 금지, A3), CLI는 0으로 종료하는지.
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
