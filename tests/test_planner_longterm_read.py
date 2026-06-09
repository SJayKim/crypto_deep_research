"""M3 AC#6: the planner's long-term READ -- watchlist/facts shape the worker set (T7b)."""

from collections.abc import Callable

from crypto_deep_research.contracts.artifact import Dimension
from crypto_deep_research.contracts.memory import LongTermMemory
from crypto_deep_research.orchestrator.planner import plan_dimensions

_REGISTRY: dict[Dimension, str] = {
    "market": "http://w/market",
    "orderbook": "http://w/orderbook",
    "sentiment": "http://w/sentiment",
    "onchain": "http://w/onchain",
}


def test_empty_memory_plans_market_only(longterm: Callable[..., LongTermMemory]) -> None:
    assert plan_dimensions("BTC", _REGISTRY, longterm()) == ["market"]


def test_watchlisted_symbol_plans_full_set(longterm: Callable[..., LongTermMemory]) -> None:
    chosen = plan_dimensions("BTC", _REGISTRY, longterm(watchlist=["BTC"]))
    assert chosen == ["market", "orderbook", "sentiment", "onchain"]


def test_fact_adds_only_the_named_dimension(longterm: Callable[..., LongTermMemory]) -> None:
    memory = longterm(facts={"BTC": ["onchain: large exchange outflow observed"]})
    assert plan_dimensions("BTC", _REGISTRY, memory) == ["market", "onchain"]
