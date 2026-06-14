"""M1 market worker: real-Anthropic behavior (T7) + deterministic MCP-down (T7b).

Also W1: the live A2A path (dispatch -> worker -> LLM) threads ``episodic_seed`` into the
market reason prompt, so a second run visibly references the first (stub LLM, T7b).

[한글 설명] ARCHITECTURE-MAP §7의 "워커 data→work→distill"에 해당(market 워커는 LLM 워커).
검증 두 갈래: (1) T7 — 실제 Anthropic 키가 있을 때만 도는 진짜 행동 테스트(의미 있는 artifact 생성),
(2) T7b — MCP가 죽으면 LLM을 부르기 전에 failed로 단락되는지(A3). 추가로 W1: 라이브 A2A
경로에서 episodic_seed(지난 런 요약)가 실제로 LLM 프롬프트에 주입되어, 두 번째 런이 첫 런을
참조하는지(Layered Memory의 episodic READ 트리거가 워커 추론까지 도달함)를 확인한다.
"""

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


# MCP 서버가 없을 때 LLM을 부르지 않고 곧장 failed artifact를 내는지. A3 단락 경로(데이터 없으면 추론 안 함).
def test_mcp_down_returns_failed_artifact() -> None:  # T7b: deterministic, no LLM
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    artifact = analyze_market("BTC", f"http://127.0.0.1:{port}/mcp")
    assert artifact.status == "failed"
    assert artifact.dimension == "market"


# [라이브 전용] 진짜 Anthropic으로 data→work→distill 전체를 돌려 비어있지 않은 artifact가
# 나오는지. T7: 워커 행동(실제 추론·증류 품질)은 실제 LLM으로만 검증한다.
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


# W1 플래그십: 진짜 A2A 디스패치(dispatch→워커→LLM) 경로에서, 넘긴 episodic_seed의
# 지난 런 headline/id가 실제 reason 프롬프트 안에 들어가는지. 시드 없으면 들어가지 않음도 확인.
# = episodic 메모리 READ가 "장식"이 아니라 워커 추론을 실제로 바꾼다는 증거(premise 5).
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
