"""DataSource: the read-only coin-data interface the MCP server is built on.

FixtureSource implements it day one; CoinGeckoSource swaps in at M5 with no agent
code change (the MCP boundary holds).
"""

from typing import Protocol

from crypto_deep_research.contracts.mcp_tools import OHLCV, News, OnchainMetrics, Orderbook


class DataSource(Protocol):
    def get_ohlcv(self, symbol: str, interval: str) -> OHLCV: ...

    def get_orderbook(self, symbol: str) -> Orderbook: ...

    def get_news(self, symbol: str) -> News: ...

    def get_onchain(self, symbol: str) -> OnchainMetrics: ...
