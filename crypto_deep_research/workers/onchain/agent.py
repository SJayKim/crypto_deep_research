"""Onchain worker: a deterministic ``data -> work`` agent over the MCP boundary.

``data`` pulls on-chain metrics from the MCP server; ``work`` reads active addresses, tx
volume, and exchange netflow directly into a bounded ``WorkerArtifact`` (A2) -- the
on-chain signal is deterministic, so no LLM (builder's call at M3, per the epic). MCP
down -> ``status="failed"`` (A3). Built on the shared ``workers/base`` harness (C6).

[한글 설명]
onchain 워커 = 가장 단순한 결정론 워커. orderbook과 같은 부류지만 계산조차 거의 없다.
- AI를 안 쓴 근거의 "등급"이 orderbook과 다르다: orderbook은 설계 문서(DESIGN)가 정해줬지만,
  onchain은 docstring이 정직하게 "builder's call at M3"(설계 결정이 아니라 구현 시점 만든 사람의
  판단)이라고 출처까지 밝힌다 — 판단의 출처를 코드에 남기는 관행.
"""

import asyncio
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from crypto_deep_research.contracts.artifact import Evidence, WorkerArtifact
from crypto_deep_research.contracts.mcp_tools import OnchainMetrics
from crypto_deep_research.workers.base import run_worker


async def _fetch_onchain(mcp_url: str, symbol: str) -> OnchainMetrics:
    async with streamable_http_client(mcp_url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("get_onchain", {"symbol": symbol})
            return OnchainMetrics.model_validate(result.structuredContent)


# _fetch_onchain / _fetch: market과 동일한 MCP 시퀀스. 호출 도구만 get_onchain으로 다르다.
def _fetch(mcp_url: str, symbol: str) -> OnchainMetrics:
    return asyncio.run(_fetch_onchain(mcp_url, symbol))


# _work: 온체인 지표 3개(활성 주소 수, 거래량, 거래소 순유출입)를 그대로 보고서에 옮기되,
#   유일한 "분석"은 순유출입 부호 해석 한 줄이다(orderbook과 달리 빈 데이터 가드도 없다 —
#   OnchainMetrics는 목록이 아니라 한 장짜리 스냅샷이라 "빈" 상태 자체가 없다). seed는 무시한다.
def _work(
    symbol: str, m: OnchainMetrics, episodic_seed: dict[str, str] | None = None
) -> WorkerArtifact:  # deterministic: prior-run seed is not used
    # netflow 부호 해석: 음수 = 코인이 거래소 밖(개인 금고)으로 = 오래 들고 가려는 축적(accumulation),
    #   양수 = 거래소 안으로 = 팔려고 들어옴 = 분산(distribution). (contracts의 해석 관례와 동일.)
    flow = "outflow (accumulation)" if m.exchange_netflow < 0 else "inflow (distribution)"
    return WorkerArtifact(
        dimension="onchain",
        status="ok",
        headline=f"{symbol}: {m.active_addresses} active addresses, net exchange {flow}",
        key_points=[
            f"active addresses {m.active_addresses}",
            f"tx volume {m.tx_volume}",
            f"exchange netflow {m.exchange_netflow}",
        ],
        evidence=[
            Evidence(metric="active_addresses", value=m.active_addresses),
            Evidence(metric="tx_volume", value=m.tx_volume),
            Evidence(metric="exchange_netflow", value=m.exchange_netflow),
        ],
    )


def analyze_onchain(
    symbol: str,
    mcp_url: str,
    episodic_seed: dict[str, str] | None = None,
    checkpointer: Any = None,
) -> WorkerArtifact:
    return run_worker("onchain", _fetch, _work, symbol, mcp_url, checkpointer=checkpointer)
