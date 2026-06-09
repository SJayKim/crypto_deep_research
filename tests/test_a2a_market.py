"""M2 A2A market worker: real JSON-RPC round-trip over a loopback socket (T8).

The deterministic tests point the worker at a dead MCP URL so ``analyze_market`` short-circuits
to ``status="failed"`` (A3) — a real over-the-wire round-trip with no Anthropic key. The live
happy-path (status="ok", real LLM) is skipif-gated like T7.
"""

import asyncio
import os
import socket
import threading
import time
from collections.abc import Callable, Iterator

import httpx
import pytest
import uvicorn
from starlette.applications import Starlette

from crypto_deep_research.contracts.a2a import AgentCard, JsonRpcResponse
from crypto_deep_research.contracts.artifact import WorkerArtifact
from crypto_deep_research.orchestrator.dispatch import dispatch_one
from crypto_deep_research.workers.market.service import build_market_app

_HAS_KEY = bool(os.environ.get("ANTHROPIC_API_KEY"))


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port: int = sock.getsockname()[1]
    sock.close()
    return port


def _serve(app: Starlette) -> tuple[str, Callable[[], None]]:
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("worker A2A service failed to start")

    def stop() -> None:
        server.should_exit = True
        thread.join(timeout=5)

    return f"http://127.0.0.1:{port}", stop


@pytest.fixture
def dead_worker_url() -> Iterator[str]:
    dead_mcp = f"http://127.0.0.1:{_free_port()}/mcp"  # nothing listening -> deterministic failed
    url, stop = _serve(build_market_app(mcp_url=dead_mcp, public_url="http://127.0.0.1:8101"))
    yield url
    stop()


def test_agent_card_served(dead_worker_url: str) -> None:  # AC#1
    response = httpx.get(f"{dead_worker_url}/.well-known/agent.json")
    card = AgentCard.model_validate(response.json())
    assert card.name == "market-worker"
    assert card.skills == ["analyze:market"]


def test_a2a_roundtrip_returns_artifact(dead_worker_url: str) -> None:  # AC#2, AC#3
    artifact = asyncio.run(dispatch_one(dead_worker_url, "BTC", "run-1"))
    assert isinstance(artifact, WorkerArtifact)
    assert artifact.dimension == "market"
    assert artifact.status == "failed"  # MCP down -> deterministic, no LLM call


def test_malformed_request_returns_jsonrpc_error(dead_worker_url: str) -> None:  # AC#4
    response = httpx.post(
        dead_worker_url,
        json={"jsonrpc": "2.0", "id": "bad", "method": "analyze", "params": {}},
    )
    assert response.status_code != 500
    rpc = JsonRpcResponse.model_validate(response.json())
    assert rpc.id == "bad"
    assert rpc.error is not None
    assert rpc.result is None


@pytest.mark.skipif(not _HAS_KEY, reason="needs real ANTHROPIC_API_KEY (T8 live)")
def test_a2a_roundtrip_live(mcp_url: str) -> None:  # T8: real LLM over the wire
    url, stop = _serve(build_market_app(mcp_url=mcp_url, public_url="http://127.0.0.1:8101"))
    try:
        artifact = asyncio.run(dispatch_one(url, "BTC", "run-live"))
        assert artifact.status == "ok"
        assert artifact.dimension == "market"
        assert artifact.headline.strip()
    finally:
        stop()
