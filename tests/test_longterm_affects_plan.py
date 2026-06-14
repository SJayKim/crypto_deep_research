"""M4 AC#2: a fact written at run end changes the next run's plan (closes the M3 READ loop).

Run 1's market worker reports something that names the onchain dimension; run end stores the
report's key points as long-term facts. Run 2's planner reads that fact and promotes onchain
into the worker set -- the long-term WRITE -> next-run READ round-trip (T7b: stub workers).

[한글 설명] ARCHITECTURE-MAP §7의 "long-term READ가 plan 변경"의 WRITE 쪽 짝. test_planner_…가
READ만 봤다면, 여기선 long-term WRITE→다음 런 READ의 완전한 왕복을 검증한다. 런1이 onchain을
언급하는 fact를 학습·저장하면, 런2의 플래너가 그 fact를 읽어 onchain 워커를 plan에 promote한다.
= long-term 메모리가 실제로 시스템을 학습시킨다(시간이 지날수록 plan이 바뀜)는 Layered Memory의
완결 증거. 실제 SqliteLongTermMemory + 스텁 워커(T7b).
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


# [스텁] 호출되면 calls에 자기 차원을 기록하고 지정한 key_points로 ok artifact를 돌려주는 가짜 워커.
# 어떤 워커가 dispatch됐는지 추적해 plan 변화를 관찰하기 위함(T7b, LLM 없음).
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


# 런1: 빈 기억 → market만 호출, 끝에 onchain을 언급하는 fact 저장. 런2: 그 fact를 읽어
# onchain을 plan에 추가 → 실제로 dispatch되고 리포트의 dimensions_ok에 포함. WRITE→READ 왕복(AC#2).
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
