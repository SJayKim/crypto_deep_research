"""Orderbook worker: a deterministic ``data -> work`` agent over the MCP boundary.

``data`` pulls top-of-book bids/asks from the MCP server; ``work`` computes spread, mid,
and depth imbalance directly into a bounded ``WorkerArtifact`` (A2) -- order-book signal
is deterministic, so no LLM (DESIGN). MCP down -> ``status="failed"`` (A3). Built on the
shared ``workers/base`` harness (C6).

[한글 설명]
orderbook 워커 = "호가창 분석가". 결정론 워커의 대표 — LLM이 없다.
- 왜 LLM이 없나: spread/mid/imbalance 같은 지표는 정의가 곧 계산식이다(같은 입력이면 항상 같은
  답). 계산기로 풀 수 있는 문제에 박사(AI)를 부르지 않는다 — 비용·지연·비결정성을 공짜로 줄인다.
- work 단계는 순수 산수로 호가창 지표를 뽑아 직접 보고서 양식에 채운다(llm_distill 미사용).
"""

import asyncio
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from crypto_deep_research.contracts.artifact import Evidence, WorkerArtifact
from crypto_deep_research.contracts.mcp_tools import Orderbook
from crypto_deep_research.workers.base import run_worker


async def _fetch_orderbook(mcp_url: str, symbol: str) -> Orderbook:
    async with streamable_http_client(mcp_url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("get_orderbook", {"symbol": symbol})
            return Orderbook.model_validate(result.structuredContent)


# _fetch_orderbook / _fetch: market과 동일한 MCP 시퀀스. 호출 도구만 get_orderbook으로 다르다.
def _fetch(mcp_url: str, symbol: str) -> Orderbook:
    return asyncio.run(_fetch_orderbook(mcp_url, symbol))


# _work: 결정론 분석. 시그니처상 episodic_seed(지난 기록)를 받지만 쓰지 않는다 — 공용 틀의 work
#   규격을 맞추려 받기만 한다(4개 워커가 한 규격을 공유하는 대가로 인자 하나를 무시).
def _work(
    symbol: str, ob: Orderbook, episodic_seed: dict[str, str] | None = None
) -> WorkerArtifact:  # deterministic: prior-run seed is not used
    # 빈 호가창 가드 (W6): 텅 빈 게시판이면 계산을 시도하지 말고 정직한 실패 보고서를 낸다.
    # 가드가 없으면 아래 계산이 0으로 나누기 오류를 내고, 그 예외가 graph 밖으로 전파돼 본부가
    #   "분석가와 연락 두절(unreachable)"로 잘못 기록한다 = 사유 오도. "게시판이 비었다"를
    #   정직하게 보고하기 위한 가드다. (가격이 0인 비정상 케이스는 이 시스템에선 생성 불가라 미가드.)
    if not ob.bids or not ob.asks:  # empty book -> no spread/mid/imbalance to compute (A3)
        return WorkerArtifact(
            dimension="orderbook",
            status="failed",
            headline=f"{symbol} orderbook empty",
            key_points=["empty orderbook"],
        )
    # 호가창에서 기초 지표 5개를 순수 산수로 뽑는다:
    #  best bid/ask = 사겠다 중 최고값 / 팔겠다 중 최저값 — 지금 당장 체결 가능한 최우선 가격.
    best_bid = max(level.price for level in ob.bids)
    best_ask = min(level.price for level in ob.asks)
    #  spread = 그 둘의 간격(좁을수록 사고팔기 쉬운 유동성 좋은 시장).
    spread = best_ask - best_bid
    #  mid = 두 값의 중간 — "현재가"의 관례적 정의.
    mid = (best_bid + best_ask) / 2
    bid_depth = sum(level.size for level in ob.bids)
    ask_depth = sum(level.size for level in ob.asks)
    #  imbalance = (사겠다 물량−팔겠다 물량)/전체, −1~+1. 양수면 사려는 쪽 줄이 더 길다.
    imbalance = (bid_depth - ask_depth) / (bid_depth + ask_depth)
    #  bps = spread를 mid 대비 만분율로 환산 — 1만원짜리와 1억원짜리 코인을 같은 잣대로 비교.
    bps = spread / mid * 1e4
    # 결정론 워커도 A2(요약 한도)를 똑같이 지킨다: 손으로 직접 보고서 양식을 채울 뿐, 핵심·근거
    #   개수와 길이는 LLM 워커와 같은 한도 안이다(증류 규칙은 본부로 가는 모든 보고서의 규칙).
    return WorkerArtifact(
        dimension="orderbook",
        status="ok",
        headline=f"{symbol} spread {spread:.1f} ({bps:.1f} bps), imbalance {imbalance:+.2f}",
        key_points=[
            f"best bid {best_bid}, best ask {best_ask}",
            f"bid depth {bid_depth:.1f}, ask depth {ask_depth:.1f}",
            f"{'bid' if imbalance > 0 else 'ask'}-heavy book",
        ],
        evidence=[
            Evidence(metric="spread", value=spread),
            Evidence(metric="mid", value=mid),
            Evidence(metric="depth_imbalance", value=round(imbalance, 4)),
        ],
    )


# analyze_orderbook: 정문. market과의 미세 차이 — episodic_seed를 run_worker에 안 넘긴다(받아도
#   안 쓰니까). 함수 겉모양(시그니처)은 공통으로 유지하되 안으로 전달만 생략했다.
def analyze_orderbook(
    symbol: str,
    mcp_url: str,
    episodic_seed: dict[str, str] | None = None,
    checkpointer: Any = None,
) -> WorkerArtifact:
    return run_worker("orderbook", _fetch, _work, symbol, mcp_url, checkpointer=checkpointer)
