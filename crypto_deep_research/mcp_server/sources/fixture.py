"""FixtureSource: serves the 4 tools from local JSON fixtures (day-one DataSource)."""

import json
from pathlib import Path
from typing import Any

from crypto_deep_research.contracts.mcp_tools import OHLCV, News, OnchainMetrics, Orderbook

_FIXTURES = Path(__file__).parent / "fixtures"


class FixtureSource:
    def __init__(self, root: Path = _FIXTURES) -> None:
        self._root = root

    def _load(self, symbol: str, tool: str) -> Any:
        path = self._root / f"{symbol.lower()}_{tool}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def get_ohlcv(self, symbol: str, interval: str = "1d") -> OHLCV:
        return OHLCV.model_validate(self._load(symbol, "ohlcv"))

    def get_orderbook(self, symbol: str) -> Orderbook:
        return Orderbook.model_validate(self._load(symbol, "orderbook"))

    def get_news(self, symbol: str) -> News:
        return News.model_validate(self._load(symbol, "news"))

    def get_onchain(self, symbol: str) -> OnchainMetrics:
        return OnchainMetrics.model_validate(self._load(symbol, "onchain"))
