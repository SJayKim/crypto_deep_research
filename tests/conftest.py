"""Shared test fixtures: an in-process MCP server over real streamable HTTP (T8 shape).

Both test_mcp_server and test_market_worker need a live MCP server on a loopback port;
this runs the FixtureSource-backed server in a uvicorn thread so tests speak real HTTP.

[한글 설명] 모든 테스트가 공유하는 fixture 모음(공통 셋업). 핵심 철학은 두 가지다.
  - T8: E2E는 "진짜 와이어"로 검증한다. 가짜 함수 호출이 아니라, 실제 uvicorn 서버를
    루프백 포트(127.0.0.1)에 띄워 진짜 HTTP/JSON-RPC로 통신한다(in-process ASGI).
  - T7b: 결정적(deterministic) 테스트는 라이브 API/LLM을 절대 부르지 않는다. 그래서
    여기 정의된 스텁(가짜 LongTerm 메모리, 가짜 느린 워커 등)으로 외부 의존을 대체한다.
이 파일이 보장하는 것: 테스트가 외부 네트워크 없이도 "진짜 프로토콜 경계"를 통과한다는 것.
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


# OS가 비어 있는 포트를 골라주게 해서(port 0) 테스트들이 포트 충돌 없이 병렬로 뜬다.
def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port: int = sock.getsockname()[1]
    sock.close()
    return port


# 세션당 한 번만 뜨는 진짜 MCP 서버(FixtureSource 기반). 워커가 MCP 클라이언트로
# 붙어 실제 streamable HTTP로 도구를 호출하는 대상(T8). 테스트 끝에 깔끔히 종료한다.
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


# 임의의 ASGI 앱(워커 서비스 등)을 즉석에서 띄워주는 헬퍼 팩토리. 워커를 별도 프로세스처럼
# 진짜 HTTP 엔드포인트로 만들어 A2A 라운드트립을 실제 와이어로 검증할 수 있게 한다(T8).
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


# [스텁] 가짜 장기기억(long-term). SQLite 대신 메모리 딕셔너리로 동작해 plan 테스트가
# 결정적이 되게 한다(T7b: DB/외부 의존 없이 watchlist·facts가 plan에 주는 영향만 검증).
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


# [스텁] 아무도 듣고 있지 않은 포트의 URL. 워커가 MCP fetch 단계에서 곧장 실패하도록 만들어
# A3 단락(short-circuit) 경로를 LLM 없이 결정적으로 재현한다(MCP 죽으면 work 안 함 → failed).
@pytest.fixture
def dead_mcp_url() -> str:
    """A loopback URL with nothing listening -> workers short-circuit to failed (A3)."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port: int = sock.getsockname()[1]
    sock.close()
    return f"http://127.0.0.1:{port}/mcp"


# [스텁] 일부러 delay초 자고 나서 ok artifact를 돌려주는 가짜 워커. fan-out 병렬성(빠른 워커는
# 안 막힘)과 timeout 차단(느린 워커는 gap)을 결정적으로 만들기 위한 도구(A3, P9 검증용).
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
