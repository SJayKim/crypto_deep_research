"""M3 AC#2 (flagship isolation, A2): a 1000-row OHLCV distills to a bounded artifact and
the orchestrator state never holds a raw array (stub LLM, T7b)."""

import asyncio
import json
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from starlette.applications import Starlette

from crypto_deep_research.contracts.artifact import Evidence
from crypto_deep_research.contracts.mcp_tools import (
    OHLCV,
    News,
    OHLCVBar,
    OnchainMetrics,
    Orderbook,
)
from crypto_deep_research.contracts.memory import LongTermMemory
from crypto_deep_research.mcp_server.server import build_server
from crypto_deep_research.orchestrator.app import run_orchestrator
from crypto_deep_research.orchestrator.dispatch import dispatch_one
from crypto_deep_research.workers.market.service import build_market_app


class _BigOhlcvSource:
    """DataSource serving a 1000-bar OHLCV -- the flagship isolation input."""

    def get_ohlcv(self, symbol: str, interval: str = "1d") -> OHLCV:
        bars = [
            OHLCVBar(
                ts=1_700_000_000 + i * 86400,
                open=100.0 + i,
                high=110.0 + i,
                low=90.0 + i,
                close=100.0 + i,
                volume=1000.0 + i,
            )
            for i in range(1000)
        ]
        return OHLCV(symbol=symbol, interval=interval, bars=bars)

    def get_orderbook(self, symbol: str) -> Orderbook:
        raise NotImplementedError

    def get_news(self, symbol: str) -> News:
        raise NotImplementedError

    def get_onchain(self, symbol: str) -> OnchainMetrics:
        raise NotImplementedError


class _FakeStructured:
    def invoke(self, prompt: str) -> Any:
        return SimpleNamespace(
            headline="stub market headline",
            key_points=["uptrend", "higher highs", "rising volume"],
            evidence=[Evidence(metric="last_close", value=1099.0)],
        )


class _FakeChat:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def invoke(self, prompt: str) -> Any:
        return SimpleNamespace(content="stub analysis")

    def with_structured_output(self, schema: Any) -> _FakeStructured:
        return _FakeStructured()


def test_thousand_row_ohlcv_distills_to_bounded_artifact(
    serve: Callable[[Starlette], str],
    longterm: Callable[..., LongTermMemory],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("crypto_deep_research.workers.base.ChatAnthropic", _FakeChat)
    assert len(_BigOhlcvSource().get_ohlcv("BTC").bars) == 1000  # the input really is big
    mcp_url = f"{serve(build_server(_BigOhlcvSource()).streamable_http_app())}/mcp"
    worker_url = serve(build_market_app(mcp_url, "http://stub"))

    artifact = asyncio.run(dispatch_one(worker_url, "BTC", "iso"))
    assert artifact.dimension == "market"
    assert artifact.status == "ok"
    assert len(artifact.key_points) <= 5  # A2 distillation cap

    report = asyncio.run(run_orchestrator("BTC", "iso", [worker_url], longterm(), 5.0))
    dumped = report.model_dump()
    assert "bars" not in json.dumps(dumped)  # no raw OHLCV array ever enters orchestrator state
    assert all(not (isinstance(v, list) and len(v) > 10) for v in dumped.values())
