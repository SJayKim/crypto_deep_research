"""CoinGeckoSource: live ``get_ohlcv`` from CoinGecko; the other 3 tools use fixtures.

The M5 live swap (AC#2) is this file + env only. ``get_ohlcv`` hits CoinGecko's
``/coins/{id}/ohlc`` (that endpoint carries no volume -> ``volume=0.0``); the remaining
tools delegate to ``FixtureSource`` so the MCP tool surface is unchanged. A 429 is
retried with backoff then raised; the worker's data node turns that into a dimension gap
(A3), never an unhandled crash (AC#4).
"""

import os
import time
from typing import Any

import httpx

from crypto_deep_research.contracts.mcp_tools import (
    OHLCV,
    News,
    OHLCVBar,
    OnchainMetrics,
    Orderbook,
)
from crypto_deep_research.mcp_server.sources.base import DataSource
from crypto_deep_research.mcp_server.sources.fixture import FixtureSource

_BASE = "https://api.coingecko.com/api/v3"
_SYMBOL_TO_ID = {"BTC": "bitcoin", "ETH": "ethereum"}
_INTERVAL_TO_DAYS = {"1d": "1", "1w": "7", "1m": "30"}
_RETRIES = 2
_BACKOFF_BASE_S = 0.5


def _retry_after(resp: httpx.Response, default: float) -> float:
    header = resp.headers.get("Retry-After")
    if header is None:
        return default
    try:
        return float(header)
    except ValueError:
        return default


class CoinGeckoSource:
    def __init__(
        self, fixture: FixtureSource | None = None, client: httpx.Client | None = None
    ) -> None:
        self._fixture = fixture or FixtureSource()
        self._client = client or httpx.Client(timeout=10.0)
        self._api_key = os.environ.get("COINGECKO_API_KEY") or ""

    def get_ohlcv(self, symbol: str, interval: str = "1d") -> OHLCV:
        coin_id = _SYMBOL_TO_ID.get(symbol.upper(), symbol.lower())
        params = {"vs_currency": "usd", "days": _INTERVAL_TO_DAYS.get(interval, "1")}
        headers = {"x-cg-demo-api-key": self._api_key} if self._api_key else {}
        rows = self._get_json(f"{_BASE}/coins/{coin_id}/ohlc", params, headers)
        bars = [
            OHLCVBar(ts=int(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=0.0)
            for r in rows
        ]
        return OHLCV(symbol=symbol.upper(), interval=interval, bars=bars)

    def get_orderbook(self, symbol: str) -> Orderbook:
        return self._fixture.get_orderbook(symbol)

    def get_news(self, symbol: str) -> News:
        return self._fixture.get_news(symbol)

    def get_onchain(self, symbol: str) -> OnchainMetrics:
        return self._fixture.get_onchain(symbol)

    def _get_json(self, url: str, params: dict[str, str], headers: dict[str, str]) -> Any:
        for attempt in range(_RETRIES):
            resp = self._client.get(url, params=params, headers=headers)
            if resp.status_code != 429:
                resp.raise_for_status()
                return resp.json()
            time.sleep(_retry_after(resp, _BACKOFF_BASE_S * 2**attempt))
        resp = self._client.get(url, params=params, headers=headers)
        resp.raise_for_status()  # a 429 on the final attempt raises -> dimension gap (AC#4)
        return resp.json()


def source_from_env() -> DataSource:
    """Pick the MCP server's data source from ``COIN_DATA_SOURCE`` (default ``fixture``)."""
    if os.environ.get("COIN_DATA_SOURCE", "fixture").lower() == "coingecko":
        return CoinGeckoSource()
    return FixtureSource()
