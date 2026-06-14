"""M4 AC#1: a second run reads the first via episodic ``last_for`` and references it.

A stub market worker records the ``episodic_seed`` it receives. The first run stores its
``RunRecord``; the second run reads it at run start and passes a compact reference down to
the worker -- the visible episodic round-trip (T7b: stub worker, no LLM).

[한글 설명] ARCHITECTURE-MAP §7의 "두 번째 런이 첫 런 참조"에 해당. 5대 개념 중 Layered Memory의
episodic 계층 — READ 트리거(런 시작 시 last_for(symbol))와 WRITE 트리거(런 끝 put)의 왕복을
검증한다. 런1은 prior가 없어 seed=None이고 자기 RunRecord를 저장. 런2는 런1을 읽어 압축된
참조(prior_run_id/prior_headline)를 워커에 내려보낸다. = episodic 메모리가 "장식"이 아니라 실제
런 간 연속성을 만든다는 premise 5의 증거. 스텁 워커(T7b).
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


# [스텁] 자기가 받은 episodic_seed를 seen 리스트에 그대로 기록하는 가짜 market 워커.
# 런마다 어떤 prior-run 참조가 내려왔는지 관찰하기 위함(T7b, LLM 없음).
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


# 런1: seed=None(첫 런) + RunRecord 저장 확인. 런2: 런1을 읽어 prior_run_id="r1",
# prior_headline=런1 headline을 워커에 전달했는지 + 최신 기록이 r2로 갱신됐는지(READ↔WRITE 왕복, AC#1).
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
