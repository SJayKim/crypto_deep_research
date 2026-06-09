"""M4 AC#2: a fact written at run end changes the next run's plan (closes the M3 READ loop).

Run 1's market worker reports something that names the onchain dimension; run end stores the
report's key points as long-term facts. Run 2's planner reads that fact and promotes onchain
into the worker set -- the long-term WRITE -> next-run READ round-trip (T7b: stub workers).
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
from crypto_deep_research.contracts.artifact import Dimension, WorkerArtifact
from crypto_deep_research.memory.longterm import SqliteLongTermMemory
from crypto_deep_research.orchestrator.app import run_orchestrator


def _stub(dimension: Dimension, key_points: list[str], calls: list[str]) -> Starlette:
    card = AgentCard(
        name=f"{dimension}-worker",
        description="stub",
        url="http://stub",
        version="0.1.0",
        skills=[f"analyze:{dimension}"],
    )

    async def agent_card(request: Request) -> Response:
        return JSONResponse(card.model_dump())

    async def analyze(request: Request) -> Response:
        raw: Any = await request.json()
        calls.append(dimension)
        artifact = WorkerArtifact(
            dimension=dimension, status="ok", headline=f"{dimension} ok", key_points=key_points
        )
        return JSONResponse(JsonRpcResponse(id=str(raw["id"]), result=artifact).model_dump())

    return Starlette(
        routes=[
            Route("/", analyze, methods=["POST"]),
            Route("/.well-known/agent.json", agent_card, methods=["GET"]),
        ]
    )


def test_run_end_fact_promotes_dimension_next_run(
    serve: Callable[[Starlette], str], tmp_path: Path
) -> None:
    calls: list[str] = []
    market_url = serve(_stub("market", ["onchain flows turned sharply negative"], calls))
    onchain_url = serve(_stub("onchain", ["large outflow"], calls))
    urls = [market_url, onchain_url]
    longterm = SqliteLongTermMemory(str(tmp_path / "orchestrator.db"))

    # Run 1: empty long-term -> planner picks market only; onchain is NOT dispatched.
    asyncio.run(run_orchestrator("BTC", "r1", urls, longterm, 5.0))
    assert calls == ["market"]
    assert any("onchain" in fact for fact in longterm.facts("BTC"))

    # Run 2: the stored fact naming onchain promotes it into the plan.
    calls.clear()
    report2 = asyncio.run(run_orchestrator("BTC", "r2", urls, longterm, 5.0))
    assert "onchain" in calls
    assert "onchain" in report2.dimensions_ok
