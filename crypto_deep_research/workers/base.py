"""Shared worker harness (C6): the A2A service + the ``data -> work`` graph skeleton.

Extracted after the 2nd worker (rule of three). Every worker is a LangGraph
``data -> work`` agent over the MCP boundary: ``data`` fetches its source via MCP and
``work`` distills it into a bounded ``WorkerArtifact`` (A2). An unreachable MCP server
short-circuits to ``status="failed"`` without ever touching the LLM (A3). LLM workers
(market, sentiment) build their artifact with ``llm_distill``; deterministic workers
(orderbook, onchain) compute it directly.
"""

import asyncio
from collections.abc import Callable
from typing import Any, TypedDict, cast

from langchain_anthropic import ChatAnthropic
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from crypto_deep_research.contracts.a2a import (
    AgentCard,
    JsonRpcError,
    JsonRpcRequest,
    JsonRpcResponse,
)
from crypto_deep_research.contracts.artifact import Dimension, Evidence, WorkerArtifact

_MODEL = "claude-sonnet-4-6"


class _Distilled(BaseModel):
    headline: str
    key_points: list[str]
    evidence: list[Evidence]


def llm_distill(dimension: Dimension, reason_prompt: str) -> WorkerArtifact:
    """Reason over the rendered source in the worker's own context, then compress (A2)."""
    reply = ChatAnthropic(model=_MODEL, temperature=0).invoke(reason_prompt)
    analysis = reply.content if isinstance(reply.content, str) else str(reply.content)
    instruction = (
        "Compress this analysis into a bounded artifact: a one-line headline, 3 to 5 key "
        "points, and at least 2 evidence items (each a metric name plus a numeric or string "
        f"value drawn from the data). Analysis:\n{analysis}"
    )
    llm = ChatAnthropic(model=_MODEL, temperature=0).with_structured_output(_Distilled)
    out = cast(_Distilled, llm.invoke(instruction))
    return WorkerArtifact(
        dimension=dimension,
        status="ok",
        headline=out.headline[:200],
        key_points=[p[:200] for p in out.key_points[:5]],
        evidence=out.evidence[:10],
    )


def seed_context(episodic_seed: dict[str, str] | None) -> str:
    """One-line prior-run note for LLM workers to reference (W1); '' when there is no prior run."""
    if not episodic_seed:
        return ""
    prior_run = episodic_seed.get("prior_run_id", "")
    prior_headline = episodic_seed.get("prior_headline", "")
    return (
        f" For continuity, the prior run ({prior_run}) concluded: {prior_headline}. "
        "Note any change since then."
    )


class WorkerState(TypedDict, total=False):
    symbol: str
    mcp_url: str
    data: Any
    artifact: WorkerArtifact
    error: str
    episodic_seed: dict[str, str] | None


def build_worker_graph(
    dimension: Dimension,
    fetch: Callable[[str, str], Any],
    work: Callable[[str, Any, dict[str, str] | None], WorkerArtifact],
    checkpointer: Any = None,
) -> Any:
    """``data`` calls ``fetch(mcp_url, symbol)`` (raises on MCP down); ``work`` distills it.

    ``checkpointer`` is the worker's own working-memory store (A4): when set, the graph's
    scratchpad state is persisted to the worker's own DB file.
    """

    def _data(state: WorkerState) -> dict[str, Any]:
        try:
            return {"data": fetch(state["mcp_url"], state["symbol"])}
        except Exception as exc:  # MCP unreachable -> failed, never raise into caller (A3)
            return {"error": f"mcp fetch failed: {type(exc).__name__}"}

    def _work(state: WorkerState) -> dict[str, Any]:
        return {"artifact": work(state["symbol"], state["data"], state.get("episodic_seed"))}

    def _fail(state: WorkerState) -> dict[str, Any]:
        artifact = WorkerArtifact(
            dimension=dimension,
            status="failed",
            headline=f"{dimension} data unavailable",
            key_points=[state["error"][:200]],
        )
        return {"artifact": artifact}

    def _route(state: WorkerState) -> str:
        return "fail" if state.get("error") else "work"

    graph = StateGraph(WorkerState)
    graph.add_node("data", _data)
    graph.add_node("work", _work)
    graph.add_node("fail", _fail)
    graph.add_edge(START, "data")
    graph.add_conditional_edges("data", _route, {"work": "work", "fail": "fail"})
    graph.add_edge("work", END)
    graph.add_edge("fail", END)
    return graph.compile(checkpointer=checkpointer)


def run_worker(
    dimension: Dimension,
    fetch: Callable[[str, str], Any],
    work: Callable[[str, Any, dict[str, str] | None], WorkerArtifact],
    symbol: str,
    mcp_url: str,
    checkpointer: Any = None,
    run_id: str = "run",
    episodic_seed: dict[str, str] | None = None,
) -> WorkerArtifact:
    graph = build_worker_graph(dimension, fetch, work, checkpointer)
    config = {"configurable": {"thread_id": run_id}} if checkpointer is not None else None
    initial = {"symbol": symbol, "mcp_url": mcp_url, "episodic_seed": episodic_seed}
    final = graph.invoke(initial, config=config)
    return cast(WorkerArtifact, final["artifact"])


def _error(rpc_id: str, code: int, message: str) -> Response:
    body = JsonRpcResponse(id=rpc_id, error=JsonRpcError(code=code, message=message))
    return JSONResponse(body.model_dump())  # JSON-RPC errors travel in a 200 envelope


def build_worker_app(
    card: AgentCard,
    analyze: Callable[[str, str, dict[str, str] | None], WorkerArtifact],
    mcp_url: str,
) -> Starlette:
    """A2A JSON-RPC service for one worker: ``POST /`` runs ``analyze``, GET serves the card."""

    async def agent_card(request: Request) -> Response:
        return JSONResponse(card.model_dump())

    async def analyze_route(request: Request) -> Response:
        try:
            raw: Any = await request.json()
        except Exception:
            return _error("", -32700, "parse error: body is not valid JSON")
        try:
            rpc = JsonRpcRequest.model_validate(raw)
        except ValidationError as exc:
            rpc_id = str(raw.get("id", "")) if isinstance(raw, dict) else ""
            return _error(rpc_id, -32600, f"invalid request: {exc.error_count()} error(s)")
        artifact = await asyncio.to_thread(
            analyze, rpc.params.symbol, mcp_url, rpc.params.episodic_seed
        )
        return JSONResponse(JsonRpcResponse(id=rpc.id, result=artifact).model_dump())

    return Starlette(
        routes=[
            Route("/", analyze_route, methods=["POST"]),
            Route("/.well-known/agent.json", agent_card, methods=["GET"]),
        ]
    )
