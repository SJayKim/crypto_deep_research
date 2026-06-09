"""Orchestrator graph (M3): plan -> dispatch -> synthesize over the worker fan-out.

``plan`` discovers the worker registry from Agent Cards and reads long-term memory to pick
the worker set (TENSION-B). ``dispatch`` fans out over A2A with ``asyncio.gather`` (P9).
``synthesize`` merges the artifacts into a ``SynthesisReport`` with per-dimension coverage
(TENSION-C). Orchestrator state holds only distilled artifacts -- never a worker's raw
context (A2).
"""

import time
from typing import Any, TypedDict, cast

from langgraph.graph import END, START, StateGraph

from crypto_deep_research.contracts.artifact import Dimension, WorkerArtifact
from crypto_deep_research.contracts.memory import EpisodicMemory, LongTermMemory, RunRecord
from crypto_deep_research.contracts.report import DimensionGap, SynthesisReport
from crypto_deep_research.orchestrator.dispatch import fan_out
from crypto_deep_research.orchestrator.planner import discover, plan_dimensions
from crypto_deep_research.orchestrator.synthesize import synthesize


class OrchestratorState(TypedDict, total=False):
    symbol: str
    run_id: str
    worker_urls: list[str]
    longterm: LongTermMemory
    timeout_s: float
    episodic_seed: dict[str, str] | None
    plan: dict[Dimension, str]
    results: list[WorkerArtifact | DimensionGap]
    report: SynthesisReport


async def _plan(state: OrchestratorState) -> dict[str, Any]:
    registry = await discover(state["worker_urls"])
    chosen = plan_dimensions(state["symbol"], registry, state["longterm"])
    return {"plan": {dimension: registry[dimension] for dimension in chosen}}


async def _dispatch(state: OrchestratorState) -> dict[str, Any]:
    results = await fan_out(
        state["plan"],
        state["symbol"],
        state["run_id"],
        state.get("timeout_s", 30.0),
        state.get("episodic_seed"),
    )
    return {"results": results}


def _synthesize(state: OrchestratorState) -> dict[str, Any]:
    return {"report": synthesize(state["symbol"], state["results"])}


def build_orchestrator() -> Any:
    graph = StateGraph(OrchestratorState)
    graph.add_node("plan", _plan)
    graph.add_node("dispatch", _dispatch)
    graph.add_node("synthesize", _synthesize)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "dispatch")
    graph.add_edge("dispatch", "synthesize")
    graph.add_edge("synthesize", END)
    return graph.compile()


def _episodic_seed(prior: RunRecord | None) -> dict[str, str] | None:
    """A compact reference to the last run, passed to workers via ``TaskParams.episodic_seed``."""
    if prior is None:
        return None
    return {"prior_run_id": prior.run_id, "prior_headline": prior.report.headline}


async def run_orchestrator(
    symbol: str,
    run_id: str,
    worker_urls: list[str],
    longterm: LongTermMemory,
    timeout_s: float = 30.0,
    episodic: EpisodicMemory | None = None,
) -> SynthesisReport:
    # Run start: read the last run for this symbol and seed it into the worker dispatch.
    seed = _episodic_seed(episodic.last_for(symbol)) if episodic is not None else None
    final = await build_orchestrator().ainvoke(
        {
            "symbol": symbol,
            "run_id": run_id,
            "worker_urls": worker_urls,
            "longterm": longterm,
            "timeout_s": timeout_s,
            "episodic_seed": seed,
        }
    )
    report = cast(SynthesisReport, final["report"])
    # Run end: store this run (episodic) and append what it learned (long-term).
    if episodic is not None:
        episodic.put(RunRecord(run_id=run_id, symbol=symbol, ts=int(time.time()), report=report))
    longterm.add_facts(symbol, report.key_points)
    return report
