"""Shared test fixtures: an in-process MCP server over real streamable HTTP (T8 shape).

Both test_mcp_server and test_market_worker need a live MCP server on a loopback port;
this runs the FixtureSource-backed server in a uvicorn thread so tests speak real HTTP.
"""

import asyncio
import socket
import threading
import time
from collections.abc import Callable, Iterator

import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from crypto_deep_research.contracts.a2a import AgentCard, JsonRpcResponse
from crypto_deep_research.contracts.artifact import Dimension, WorkerArtifact
from crypto_deep_research.contracts.memory import LongTermMemory
from crypto_deep_research.mcp_server.server import build_server


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port: int = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture(scope="session")
def mcp_url() -> Iterator[str]:
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            build_server().streamable_http_app(),
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("MCP test server failed to start")
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def serve() -> Iterator[Callable[[Starlette], str]]:
    """Start ASGI apps on free loopback ports; return each base URL; stop all at teardown."""
    running: list[tuple[uvicorn.Server, threading.Thread]] = []

    def _start(app: Starlette) -> str:
        port = _free_port()
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        else:
            raise RuntimeError("test server failed to start")
        running.append((server, thread))
        return f"http://127.0.0.1:{port}"

    yield _start
    for server, thread in running:
        server.should_exit = True
        thread.join(timeout=5)


class _StubLongTerm:
    """Deterministic LongTermMemory for planner/orchestrator tests (T7b)."""

    def __init__(self, watchlist: list[str], facts: dict[str, list[str]]) -> None:
        self._watchlist = watchlist
        self._facts = facts

    def watchlist(self) -> list[str]:
        return self._watchlist

    def facts(self, symbol: str) -> list[str]:
        return self._facts.get(symbol, [])

    def add_facts(self, symbol: str, facts: list[str]) -> None:
        self._facts.setdefault(symbol, []).extend(facts)


@pytest.fixture
def longterm() -> Callable[..., LongTermMemory]:
    """Factory: ``longterm(watchlist=[...], facts={...})`` -> a stub LongTermMemory."""

    def _make(
        watchlist: list[str] | None = None, facts: dict[str, list[str]] | None = None
    ) -> LongTermMemory:
        return _StubLongTerm(watchlist or [], facts or {})

    return _make


@pytest.fixture
def dead_mcp_url() -> str:
    """A loopback URL with nothing listening -> workers short-circuit to failed (A3)."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port: int = sock.getsockname()[1]
    sock.close()
    return f"http://127.0.0.1:{port}/mcp"


@pytest.fixture
def slow_app() -> Callable[[Dimension, float], Starlette]:
    """Factory for a stub worker that sleeps ``delay`` then returns an ok artifact."""

    def _make(dimension: Dimension, delay: float) -> Starlette:
        card = AgentCard(
            name=f"{dimension}-worker",
            description="slow stub",
            url="http://stub",
            version="0.1.0",
            skills=[f"analyze:{dimension}"],
        )

        async def agent_card(request: Request) -> Response:
            return JSONResponse(card.model_dump())

        async def analyze(request: Request) -> Response:
            await asyncio.sleep(delay)
            raw = await request.json()
            artifact = WorkerArtifact(
                dimension=dimension, status="ok", headline="slow ok", key_points=["done"]
            )
            return JSONResponse(JsonRpcResponse(id=str(raw["id"]), result=artifact).model_dump())

        return Starlette(
            routes=[
                Route("/", analyze, methods=["POST"]),
                Route("/.well-known/agent.json", agent_card, methods=["GET"]),
            ]
        )

    return _make
