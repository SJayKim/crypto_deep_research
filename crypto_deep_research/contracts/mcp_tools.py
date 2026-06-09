"""MCP tool I/O schemas: get_ohlcv, get_orderbook, get_news, get_onchain."""

from pydantic import BaseModel


class OHLCVBar(BaseModel):
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class OHLCV(BaseModel):
    symbol: str
    interval: str
    bars: list[OHLCVBar]


class OrderbookLevel(BaseModel):
    price: float
    size: float


class Orderbook(BaseModel):
    symbol: str
    bids: list[OrderbookLevel]
    asks: list[OrderbookLevel]


class NewsItem(BaseModel):
    title: str
    source: str
    sentiment: float  # -1.0..1.0


class News(BaseModel):
    symbol: str
    items: list[NewsItem]


class OnchainMetrics(BaseModel):
    symbol: str
    active_addresses: int
    tx_volume: float
    exchange_netflow: float
