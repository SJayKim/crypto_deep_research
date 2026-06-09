"""M4 AC#1: a second run reads the first via episodic ``last_for`` and references it.

A stub market worker records the ``episodic_seed`` it receives. The first run stores its
``RunRecord``; the second run reads it at run start and passes a compact reference down to
the worker -- the visible episodic round-trip (T7b: stub worker, no LLM).
"""

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from crypto_deep_research.contracts.a2a import AgentCard, JsonRpcResponse
from crypto_deep_research.contracts.artifact import WorkerArtifact
from crypto_deep_research.contracts.memory import LongTermMemory
from crypto_deep_research.memory.episodic import SqliteEpisodicMemory
from crypto_deep_research.orchestrator.app import run_orchestrator


def _seed_recording_market(seen: list[dict[str, str] | None]) -> Starlette:
    card = AgentCard(
        name="market-worker",
        description="stub",
        url="http://stub",
        version="0.1.0",
        skills=["analyze:market"],
    )

    async def agent_card(request: Request) -> Response:
        return JSONResponse(card.model_dump())

    async def analyze(request: Request) -> Response:
        raw: Any = await request.json()
        seen.append(raw["params"].get("episodic_seed"))
        artifact = WorkerArtifact(
            dimension="market", status="ok", headline="market ok", key_points=["steady"]
        )
        return JSONResponse(JsonRpcResponse(id=str(raw["id"]), result=artifact).model_dump())

    return Starlette(
        routes=[
            Route("/", analyze, methods=["POST"]),
            Route("/.well-known/agent.json", agent_card, methods=["GET"]),
        ]
    )


def test_second_run_reads_and_references_first(
    serve: Callable[[Starlette], str],
    longterm: Callable[..., LongTermMemory],
    tmp_path: Path,
) -> None:
    seen: list[dict[str, str] | None] = []
    url = serve(_seed_recording_market(seen))
    episodic = SqliteEpisodicMemory(str(tmp_path / "orchestrator.db"))

    report1 = asyncio.run(run_orchestrator("BTC", "r1", [url], longterm(), 5.0, episodic=episodic))
    # First run: nothing prior -> no seed; the run is now stored.
    assert seen == [None]
    stored = episodic.last_for("BTC")
    assert stored is not None and stored.run_id == "r1"

    asyncio.run(run_orchestrator("BTC", "r2", [url], longterm(), 5.0, episodic=episodic))
    # Second run visibly references the first via the episodic seed it passed to the worker.
    second_seed = seen[1]
    assert second_seed is not None
    assert second_seed["prior_run_id"] == "r1"
    assert second_seed["prior_headline"] == report1.headline

    latest = episodic.last_for("BTC")
    assert latest is not None and latest.run_id == "r2"
