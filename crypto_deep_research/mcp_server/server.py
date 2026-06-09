"""MCP server: 4 read-only coin-data tools over streamable HTTP, backed by a DataSource.

Stateless and read-only (A4): every tool call reads the source and returns; no shared
mutable state, so concurrent calls return identical data. Run with:
``python -m crypto_deep_research.mcp_server.server`` (streamable HTTP on 127.0.0.1:8000/mcp).
"""

from mcp.server.fastmcp import FastMCP

from crypto_deep_research.contracts.mcp_tools import OHLCV, News, OnchainMetrics, Orderbook
from crypto_deep_research.mcp_server.sources.base import DataSource
from crypto_deep_research.mcp_server.sources.fixture import FixtureSource


def build_server(source: DataSource | None = None, host: str | None = None) -> FastMCP:
    src: DataSource = source or FixtureSource()
    # host set (e.g. 0.0.0.0 under compose) binds non-localhost and skips FastMCP's
    # localhost-only DNS-rebinding guard so in-cluster workers can reach it; None = default.
    mcp = FastMCP("coin-data", host=host) if host else FastMCP("coin-data")

    @mcp.tool()
    def get_ohlcv(symbol: str, interval: str = "1d") -> OHLCV:
        """Recent OHLCV bars for a symbol."""
        return src.get_ohlcv(symbol, interval)

    @mcp.tool()
    def get_orderbook(symbol: str) -> Orderbook:
        """Top-of-book bids and asks for a symbol."""
        return src.get_orderbook(symbol)

    @mcp.tool()
    def get_news(symbol: str) -> News:
        """Recent news headlines with sentiment for a symbol."""
        return src.get_news(symbol)

    @mcp.tool()
    def get_onchain(symbol: str) -> OnchainMetrics:
        """On-chain activity metrics for a symbol."""
        return src.get_onchain(symbol)

    return mcp


if __name__ == "__main__":
    build_server().run(transport="streamable-http")
