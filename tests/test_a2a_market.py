"""M2 A2A market worker: real JSON-RPC round-trip over a loopback socket (T8).

The deterministic tests point the worker at a dead MCP URL so ``analyze_market`` short-circuits
to ``status="failed"`` (A3) — a real over-the-wire round-trip with no Anthropic key. The live
happy-path (status="ok", real LLM) is skipif-gated like T7.

[한글 설명] ARCHITECTURE-MAP §7의 "A2A 와이어 라운드트립"에 해당. 5대 개념 중 'A2A(에이전트↔
에이전트)'의 핵심 검증. A1 결정대로 직접 짠 JSON-RPC 2.0 + 정적 Agent Card를 쓴다. 워커를
실제 소켓에 띄우고 오케스트레이터가 진짜 HTTP로 호출(T8)해, Agent Card 제공·정상 라운드트립·
잘못된 요청 시 500이 아닌 JSON-RPC error 응답을 확인한다. MCP를 죽여 LLM 없이 결정적으로 돌린다(A3).
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


# 워커가 /.well-known/agent.json으로 Agent Card를 제공하는지(A1 정적 카드, A2A 발견의 시작점).
def test_agent_card_served(dead_worker_url: str) -> None:  # AC#1
    response = httpx.get(f"{dead_worker_url}/.well-known/agent.json")
    card = AgentCard.model_validate(response.json())
    assert card.name == "market-worker"
    assert card.skills == ["analyze:market"]


# 오케스트레이터가 A2A로 워커를 호출하면 WorkerArtifact가 와이어를 타고 돌아오는지.
# MCP 죽음 → failed로 결정적(A3). JSON-RPC 라운드트립이 진짜로 동작한다는 증거.
def test_a2a_roundtrip_returns_artifact(dead_worker_url: str) -> None:  # AC#2, AC#3
    artifact = asyncio.run(dispatch_one(dead_worker_url, "BTC", "run-1"))
    assert isinstance(artifact, WorkerArtifact)
    assert artifact.dimension == "market"
    assert artifact.status == "failed"  # MCP down -> deterministic, no LLM call


# 잘못된 요청(필수 params 없음)에 서버가 500으로 죽지 않고 규격 맞는 JSON-RPC error를 내는지.
# A2A가 진짜 프로토콜답게 오류를 구조화해 돌려준다는 보장.
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


# [라이브 전용] 진짜 LLM으로 A2A 정상 경로(status="ok")가 와이어를 타고 동작하는지(T8 live).
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
