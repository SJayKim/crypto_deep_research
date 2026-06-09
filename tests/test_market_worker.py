"""M1 market worker: real-Anthropic behavior (T7) + deterministic MCP-down (T7b)."""

import os
import socket

import pytest

from crypto_deep_research.workers.market.agent import analyze_market

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
