"""Working memory: a worker's per-run scratchpad, durably backed by its own checkpointer DB.

The LangGraph checkpointer is the storage mechanism (DESIGN): the ``data -> work`` graph's
state IS the scratchpad -- ``data`` writes it, ``work`` reads it -- and the checkpointer
persists it. A4: each worker owns its own checkpointer DB file, distinct from the
orchestrator's episodic/long-term DB. The caller owns the checkpointer's lifetime.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from crypto_deep_research.contracts.artifact import Dimension


def working_db_path(memory_dir: str, dimension: Dimension) -> str:
    """A worker's own checkpointer DB path (one file per worker, A4)."""
    return str(Path(memory_dir) / f"working-{dimension}.db")


@contextmanager
def worker_checkpointer(db_path: str) -> Iterator[SqliteSaver]:
    """Open a worker's own SQLite checkpointer at ``db_path`` (single-writer-per-file, A4)."""
    with SqliteSaver.from_conn_string(db_path) as saver:
        saver.setup()
        yield saver
