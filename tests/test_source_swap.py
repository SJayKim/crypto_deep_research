"""M5 source swap (AC#2/#3/#4): CoinGeckoSource serves get_ohlcv live and delegates the
other 3 tools to fixtures; the COIN_DATA_SOURCE env flips the source; a persistent 429
surfaces as a dimension gap, not a crash. Deterministic -- CoinGecko HTTP is a MockTransport,
no network and no LLM (CLAUDE.md: no live API in tests)."""

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from crypto_deep_research.contracts.artifact import WorkerArtifact
from crypto_deep_research.contracts.mcp_tools import OHLCV
from crypto_deep_research.mcp_server.sources.coingecko import CoinGeckoSource, source_from_env
from crypto_deep_research.mcp_server.sources.fixture import FixtureSource
from crypto_deep_research.workers.base import build_worker_graph

_OHLC_PAYLOAD = [
    [1704067200000, 42000.0, 42500.0, 41800.0, 42300.0],
    [1704153600000, 42300.0, 43000.0, 42100.0, 42800.0],
]


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_get_ohlcv_parses_coingecko_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/coins/bitcoin/ohlc" in str(request.url)
        return httpx.Response(200, json=_OHLC_PAYLOAD)

    result = CoinGeckoSource(client=_client(handler)).get_ohlcv("BTC")
    assert isinstance(result, OHLCV)
    assert result.symbol == "BTC"
    assert len(result.bars) == 2
    assert result.bars[0].close == 42300.0
    assert all(bar.volume == 0.0 for bar in result.bars)  # /ohlc carries no volume


def test_other_tools_delegate_to_fixture() -> None:
    # The HTTP client must never be touched for the 3 delegated tools.
    src = CoinGeckoSource(client=_client(lambda r: httpx.Response(500)))
    assert src.get_orderbook("BTC") == FixtureSource().get_orderbook("BTC")
    assert src.get_news("BTC") == FixtureSource().get_news("BTC")
    assert src.get_onchain("BTC") == FixtureSource().get_onchain("BTC")


def test_persistent_429_raises_clean_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "0"})

    src = CoinGeckoSource(client=_client(handler))
    with pytest.raises(httpx.HTTPStatusError):
        src.get_ohlcv("BTC")


def test_429_surfaces_as_dimension_gap() -> None:
    req = httpx.Request("GET", "http://coingecko/ohlc")
    resp = httpx.Response(429, request=req)

    def fetch(mcp_url: str, symbol: str) -> Any:
        raise httpx.HTTPStatusError("rate limited", request=req, response=resp)

    def work(symbol: str, data: Any, episodic_seed: dict[str, str] | None = None) -> WorkerArtifact:
        raise AssertionError("work must not run when fetch fails")

    final = build_worker_graph("market", fetch, work).invoke(
        {"symbol": "BTC", "mcp_url": "http://mcp"}
    )
    artifact = final["artifact"]
    assert artifact.status == "failed"
    assert artifact.dimension == "market"


def test_source_from_env_swaps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COIN_DATA_SOURCE", raising=False)
    assert isinstance(source_from_env(), FixtureSource)
    monkeypatch.setenv("COIN_DATA_SOURCE", "coingecko")
    assert isinstance(source_from_env(), CoinGeckoSource)
