"""M3 orderbook worker: deterministic spread/mid/imbalance arithmetic + Agent Card (W3).

The orderbook worker is deterministic (no LLM), so ``_work`` is unit-tested directly with
fixture order books. The empty-book case asserts the 0-depth/0-mid guard (W6).
"""

from collections.abc import Callable

import httpx
from starlette.applications import Starlette

from crypto_deep_research.contracts.a2a import AgentCard
from crypto_deep_research.contracts.mcp_tools import Orderbook, OrderbookLevel
from crypto_deep_research.workers.orderbook.agent import _work
from crypto_deep_research.workers.orderbook.service import build_orderbook_app


def _evidence(artifact: object) -> dict[str, float | str]:
    return {e.metric: e.value for e in artifact.evidence}  # type: ignore[attr-defined]


def test_work_computes_spread_mid_imbalance_bid_heavy() -> None:
    ob = Orderbook(
        symbol="BTC",
        bids=[OrderbookLevel(price=100.0, size=4.0), OrderbookLevel(price=99.0, size=4.0)],
        asks=[OrderbookLevel(price=101.0, size=1.0), OrderbookLevel(price=102.0, size=1.0)],
    )
    art = _work("BTC", ob)
    ev = _evidence(art)
    assert art.status == "ok"
    assert art.dimension == "orderbook"
    assert ev["spread"] == 1.0  # best_ask 101 - best_bid 100
    assert ev["mid"] == 100.5  # (100 + 101) / 2
    assert ev["depth_imbalance"] == 0.6  # (8 - 2) / (8 + 2)
    assert any("bid-heavy" in p for p in art.key_points)


def test_work_negative_imbalance_ask_heavy() -> None:
    ob = Orderbook(
        symbol="BTC",
        bids=[OrderbookLevel(price=100.0, size=1.0)],
        asks=[OrderbookLevel(price=101.0, size=4.0)],
    )
    art = _work("BTC", ob)
    ev = _evidence(art)
    assert ev["depth_imbalance"] == -0.6  # (1 - 4) / (1 + 4)
    assert any("ask-heavy" in p for p in art.key_points)


def test_empty_book_returns_failed() -> None:  # W6 guard
    ob = Orderbook(symbol="BTC", bids=[], asks=[])
    art = _work("BTC", ob)
    assert art.status == "failed"
    assert art.dimension == "orderbook"


def test_agent_card_skills(serve: Callable[[Starlette], str]) -> None:
    app = build_orderbook_app(mcp_url="http://127.0.0.1:1/mcp", public_url="http://stub")
    base = serve(app)
    card = AgentCard.model_validate(httpx.get(f"{base}/.well-known/agent.json").json())
    assert card.name == "orderbook-worker"
    assert card.skills == ["analyze:orderbook"]
