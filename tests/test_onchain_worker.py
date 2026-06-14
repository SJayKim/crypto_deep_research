"""M3 onchain worker: deterministic netflow-direction classification + Agent Card (W3).

The onchain worker is deterministic (no LLM), so ``_work`` is unit-tested directly with
fixture metrics covering both netflow directions.

[한글 설명] onchain 워커 검증. 설계상 결정적(deterministic) 워커라 LLM이 없다 — 거래소
netflow 부호를 산술/규칙으로 직접 분류한다(음수=유출=축적, 양수=유입=분산). 따라서 LLM 스텁
없이 _work를 직접 단위 테스트한다. 또 A2A discover에 쓰이는 Agent Card(skills="analyze:onchain")가
제대로 제공되는지 확인 — 워커 레지스트리가 데이터 주도(AC#7)로 구성되는 토대.
"""

from collections.abc import Callable

import httpx
from starlette.applications import Starlette

from crypto_deep_research.contracts.a2a import AgentCard
from crypto_deep_research.contracts.mcp_tools import OnchainMetrics
from crypto_deep_research.workers.onchain.agent import _work
from crypto_deep_research.workers.onchain.service import build_onchain_app


# 음수 netflow → "유출(축적)"로 분류하고 evidence에 원수치를 그대로 담는지. 결정적 규칙 검증.
def test_work_negative_netflow_is_outflow_accumulation() -> None:
    m = OnchainMetrics(symbol="BTC", active_addresses=900000, tx_volume=12.5, exchange_netflow=-3.0)
    art = _work("BTC", m)
    assert art.status == "ok"
    assert art.dimension == "onchain"
    assert "outflow (accumulation)" in art.headline
    ev = {e.metric: e.value for e in art.evidence}
    assert ev["exchange_netflow"] == -3.0
    assert ev["active_addresses"] == 900000


# 양수 netflow → "유입(분산)"으로 반대 방향 분류. 부호에 따른 분기 양쪽을 다 덮는다.
def test_work_positive_netflow_is_inflow_distribution() -> None:
    m = OnchainMetrics(symbol="BTC", active_addresses=900000, tx_volume=12.5, exchange_netflow=3.0)
    art = _work("BTC", m)
    assert "inflow (distribution)" in art.headline


# Agent Card가 이름·skills를 정확히 노출하는지. 오케스트레이터 discover가 이 카드로
# 차원→워커 URL 레지스트리를 만든다(A2A 발견, AC#7).
def test_agent_card_skills(serve: Callable[[Starlette], str]) -> None:
    app = build_onchain_app(mcp_url="http://127.0.0.1:1/mcp", public_url="http://stub")
    base = serve(app)
    card = AgentCard.model_validate(httpx.get(f"{base}/.well-known/agent.json").json())
    assert card.name == "onchain-worker"
    assert card.skills == ["analyze:onchain"]
