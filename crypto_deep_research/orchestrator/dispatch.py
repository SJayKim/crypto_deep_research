"""A2A dispatch + fan-out: call workers' ``analyze`` over JSON-RPC, return artifacts.

``dispatch_one`` is the M2 single-worker call. ``fan_out`` runs the chosen worker set
concurrently with ``asyncio.gather`` over A2A (P9 -- NOT LangGraph ``Send``, which cannot
cross the process boundary). Each worker runs under a single per-worker wall-clock deadline
(A3) enforced by ``asyncio.wait_for``: a slow or unreachable worker becomes a ``DimensionGap``
instead of blocking the gather or raising. The orchestrator receives only the
``WorkerArtifact`` -- never the worker's internal context.
"""

import asyncio

import httpx

from crypto_deep_research.contracts.a2a import JsonRpcRequest, JsonRpcResponse, TaskParams
from crypto_deep_research.contracts.artifact import Dimension, WorkerArtifact
from crypto_deep_research.contracts.report import DimensionGap

DEFAULT_TIMEOUT_S = 30.0


async def dispatch_one(
    worker_url: str,
    symbol: str,
    run_id: str,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    episodic_seed: dict[str, str] | None = None,
) -> WorkerArtifact:
    request = JsonRpcRequest(
        id=run_id,
        method="analyze",
        params=TaskParams(symbol=symbol, run_id=run_id, episodic_seed=episodic_seed),
    )
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        http_response = await client.post(worker_url, json=request.model_dump())
    response = JsonRpcResponse.model_validate(http_response.json())
    if response.error is not None or response.result is None:
        message = response.error.message if response.error else "empty result"
        raise RuntimeError(f"worker {worker_url} returned a JSON-RPC error: {message}")
    return response.result


async def _dispatch_or_gap(
    dimension: Dimension,
    worker_url: str,
    symbol: str,
    run_id: str,
    timeout_s: float,
    episodic_seed: dict[str, str] | None,
) -> WorkerArtifact | DimensionGap:
    try:
        return await asyncio.wait_for(
            dispatch_one(worker_url, symbol, run_id, timeout_s, episodic_seed),
            timeout_s,
        )
    except (TimeoutError, httpx.TimeoutException):  # wall-clock (A3) or HTTP-op timeout -> gap
        return DimensionGap(dimension=dimension, reason="timeout")
    except Exception as exc:  # unreachable / transport / bad envelope -> a gap, never raise
        return DimensionGap(dimension=dimension, reason=f"unreachable: {type(exc).__name__}")


async def fan_out(
    plan: dict[Dimension, str],
    symbol: str,
    run_id: str,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    episodic_seed: dict[str, str] | None = None,
) -> list[WorkerArtifact | DimensionGap]:
    """Dispatch every (dimension, url) in ``plan`` concurrently; total latency ~ slowest."""
    tasks = [
        _dispatch_or_gap(dimension, url, symbol, run_id, timeout_s, episodic_seed)
        for dimension, url in plan.items()
    ]
    return list(await asyncio.gather(*tasks))
