"""M4 AC#3 + AC#4: DB topology (A4).

Each worker owns its own checkpointer DB file, distinct from the orchestrator's episodic +
long-term DB (AC#3). Workers running concurrently write only their own files; the
orchestrator DB stays byte-for-byte untouched -- single-writer-per-file (AC#4). Deterministic
stubs, no MCP or LLM (T7b).
"""

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from starlette.applications import Starlette

from crypto_deep_research.contracts.artifact import Dimension, WorkerArtifact
from crypto_deep_research.memory.episodic import SqliteEpisodicMemory
from crypto_deep_research.memory.longterm import SqliteLongTermMemory
from crypto_deep_research.memory.working import worker_checkpointer, working_db_path
from crypto_deep_research.orchestrator.dispatch import dispatch_one
from crypto_deep_research.workers.base import run_worker
from crypto_deep_research.workers.orderbook.service import build_orderbook_app

_DIMENSIONS: tuple[Dimension, ...] = ("market", "orderbook", "sentiment", "onchain")


def _fetch(mcp_url: str, symbol: str) -> dict[str, str]:
    return {"symbol": symbol}  # deterministic stub: no MCP


def _work_for(dimension: Dimension) -> Callable[[str, Any, dict[str, str] | None], WorkerArtifact]:
    def work(symbol: str, data: Any, episodic_seed: dict[str, str] | None = None) -> WorkerArtifact:
        return WorkerArtifact(dimension=dimension, status="ok", headline="ok", key_points=["x"])

    return work


def _run_one(dimension: Dimension, memory_dir: str) -> WorkerArtifact:
    # Each worker opens its OWN checkpointer DB inside its own thread (single-writer).
    with worker_checkpointer(working_db_path(memory_dir, dimension)) as cp:
        return run_worker(dimension, _fetch, _work_for(dimension), "BTC", "unused", cp, "run")


def test_db_topology_and_single_writer(tmp_path: Path) -> None:
    memory_dir = str(tmp_path)
    orch_db = str(tmp_path / "orchestrator.db")

    # Orchestrator owns one DB file for episodic + long-term; seed it, then snapshot its bytes.
    longterm = SqliteLongTermMemory(orch_db)
    SqliteEpisodicMemory(orch_db)
    longterm.add_facts("BTC", ["seeded"])
    before = Path(orch_db).read_bytes()

    # AC#3: each worker's checkpointer DB path is distinct from the orchestrator DB and unique.
    worker_paths = [working_db_path(memory_dir, d) for d in _DIMENSIONS]
    assert orch_db not in worker_paths
    assert len(set(worker_paths)) == len(worker_paths)

    # AC#4: run all workers concurrently, each writing its own checkpointer DB.
    async def _run_all() -> None:
        await asyncio.gather(*[asyncio.to_thread(_run_one, d, memory_dir) for d in _DIMENSIONS])

    asyncio.run(_run_all())

    # Each worker wrote its own file; the orchestrator DB is byte-for-byte untouched.
    for path in worker_paths:
        assert Path(path).exists()
    assert Path(orch_db).read_bytes() == before


def test_live_serving_path_writes_working_db(
    serve: Callable[[Starlette], str], dead_mcp_url: str, tmp_path: Path
) -> None:
    # W2: the LIVE A2A serving path injects the worker's own checkpointer, so a real dispatch
    # writes its working-<dim>.db (DESIGN premise 5: every layer has a real trigger). Dead MCP
    # -> deterministic failed artifact, so no MCP/LLM is needed (T7b).
    db_path = working_db_path(str(tmp_path), "orderbook")
    with worker_checkpointer(db_path) as cp:
        worker_url = serve(build_orderbook_app(dead_mcp_url, "http://stub", cp))
        artifact = asyncio.run(dispatch_one(worker_url, "BTC", "run"))
        assert artifact.dimension == "orderbook" and artifact.status == "failed"
        assert Path(db_path).exists()
        assert list(cp.list(None))  # the live run actually wrote checkpoints to the worker's DB
