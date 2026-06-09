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

from crypto_deep_research.contracts.artifact import Dimension, WorkerArtifact
from crypto_deep_research.memory.episodic import SqliteEpisodicMemory
from crypto_deep_research.memory.longterm import SqliteLongTermMemory
from crypto_deep_research.memory.working import worker_checkpointer, working_db_path
from crypto_deep_research.workers.base import run_worker

_DIMENSIONS: tuple[Dimension, ...] = ("market", "orderbook", "sentiment", "onchain")


def _fetch(mcp_url: str, symbol: str) -> dict[str, str]:
    return {"symbol": symbol}  # deterministic stub: no MCP


def _work_for(dimension: Dimension) -> Callable[[str, Any], WorkerArtifact]:
    def work(symbol: str, data: Any) -> WorkerArtifact:
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
