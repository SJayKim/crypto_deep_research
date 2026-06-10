"""M3 onchain worker: deterministic netflow-direction classification + Agent Card (W3).

The onchain worker is deterministic (no LLM), so ``_work`` is unit-tested directly with
fixture metrics covering both netflow directions.
"""

from collections.abc import Callable

import httpx
from starlette.applications import Starlette

from crypto_deep_research.contracts.a2a import AgentCard
from crypto_deep_research.contracts.mcp_tools import OnchainMetrics
from crypto_deep_research.workers.onchain.agent import _work
from crypto_deep_research.workers.onchain.service import build_onchain_app


def test_work_negative_netflow_is_outflow_accumulation() -> None:
    m = OnchainMetrics(symbol="BTC", active_addresses=900000, tx_volume=12.5, exchange_netflow=-3.0)
    art = _work("BTC", m)
    assert art.status == "ok"
    assert art.dimension == "onchain"
    assert "outflow (accumulation)" in art.headline
    ev = {e.metric: e.value for e in art.evidence}
    assert ev["exchange_netflow"] == -3.0
    assert ev["active_addresses"] == 900000


def test_work_positive_netflow_is_inflow_distribution() -> None:
    m = OnchainMetrics(symbol="BTC", active_addresses=900000, tx_volume=12.5, exchange_netflow=3.0)
    art = _work("BTC", m)
    assert "inflow (distribution)" in art.headline


def test_agent_card_skills(serve: Callable[[Starlette], str]) -> None:
    app = build_onchain_app(mcp_url="http://127.0.0.1:1/mcp", public_url="http://stub")
    base = serve(app)
    card = AgentCard.model_validate(httpx.get(f"{base}/.well-known/agent.json").json())
    assert card.name == "onchain-worker"
    assert card.skills == ["analyze:onchain"]
