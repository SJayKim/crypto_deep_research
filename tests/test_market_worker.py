"""M1 market worker: real-Anthropic behavior (T7) + deterministic MCP-down (T7b).

Also W1: the live A2A path (dispatch -> worker -> LLM) threads ``episodic_seed`` into the
market reason prompt, so a second run visibly references the first (stub LLM, T7b)."""

import asyncio
import os
import socket
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
from crypto_deep_research.mcp_server.server import build_server
from crypto_deep_research.orchestrator.dispatch import dispatch_one
from crypto_deep_research.workers.market.agent import analyze_market
from crypto_deep_research.workers.market.service import build_market_app

_HAS_KEY = bool(os.environ.get("ANTHROPIC_API_KEY"))


def test_mcp_down_returns_failed_artifact() -> None:  # T7b: deterministic, no LLM
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    artifact = analyze_market("BTC", f"http://127.0.0.1:{port}/mcp")
    assert artifact.status == "failed"
    assert artifact.dimension == "market"


@pytest.mark.skipif(not _HAS_KEY, reason="needs real ANTHROPIC_API_KEY (T7)")
def test_market_worker_produces_nontrivial_artifact(mcp_url: str) -> None:  # T7: real Anthropic
    artifact = analyze_market("BTC", mcp_url)
    assert artifact.status == "ok"
    assert artifact.dimension == "market"
    assert artifact.headline.strip()
    assert len(artifact.key_points) >= 1
    assert len(artifact.evidence) >= 1


class _SmallOhlcvSource:
    """A tiny OHLCV source for the live worker path (W1); other tools are unused here."""

    def get_ohlcv(self, symbol: str, interval: str = "1d") -> OHLCV:
        bars = [
            OHLCVBar(ts=1_700_000_000, open=100.0, high=110.0, low=90.0, close=100.0, volume=10.0),
            OHLCVBar(ts=1_700_086_400, open=100.0, high=120.0, low=95.0, close=115.0, volume=12.0),
        ]
        return OHLCV(symbol=symbol, interval=interval, bars=bars)

    def get_orderbook(self, symbol: str) -> Orderbook:
        raise NotImplementedError

    def get_news(self, symbol: str) -> News:
        raise NotImplementedError

    def get_onchain(self, symbol: str) -> OnchainMetrics:
        raise NotImplementedError


class _CapturingStructured:
    def invoke(self, prompt: str) -> Any:
        return SimpleNamespace(
            headline="stub", key_points=["a", "b"], evidence=[Evidence(metric="x", value=1.0)]
        )


class _CapturingChat:
    """Stub LLM that records the reason prompt market ``_work`` builds (T7b, no real Anthropic)."""

    prompts: list[str] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def invoke(self, prompt: str) -> Any:
        _CapturingChat.prompts.append(prompt)
        return SimpleNamespace(content="stub analysis")

    def with_structured_output(self, schema: Any) -> _CapturingStructured:
        return _CapturingStructured()


def test_episodic_seed_reaches_live_market_prompt(
    serve: Callable[[Starlette], str], monkeypatch: pytest.MonkeyPatch
) -> None:  # W1: the live A2A path threads episodic_seed into the worker's LLM prompt
    _CapturingChat.prompts = []
    monkeypatch.setattr("crypto_deep_research.workers.base.ChatAnthropic", _CapturingChat)
    mcp_url = f"{serve(build_server(_SmallOhlcvSource()).streamable_http_app())}/mcp"
    worker_url = serve(build_market_app(mcp_url, "http://stub"))
    seed = {"prior_run_id": "r1", "prior_headline": "BTC trending up"}

    asyncio.run(dispatch_one(worker_url, "BTC", "r2", episodic_seed=seed))
    seeded_prompt = _CapturingChat.prompts[0]  # the reason prompt market _work handed the LLM
    assert "BTC trending up" in seeded_prompt  # prior-run headline referenced on the live path
    assert "r1" in seeded_prompt

    _CapturingChat.prompts = []
    asyncio.run(dispatch_one(worker_url, "BTC", "r3"))  # no seed -> no prior-run reference
    assert "BTC trending up" not in _CapturingChat.prompts[0]
