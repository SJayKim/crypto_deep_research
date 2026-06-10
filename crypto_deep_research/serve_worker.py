"""Process entry for one worker: ``python -m crypto_deep_research.serve_worker``.

Lives outside ``workers/`` on purpose: it's packaging, not agent code, so the M5 live
swap leaves ``workers/`` and ``orchestrator/`` byte-for-byte unchanged (AC#2). Env-driven
so a worker container is just an image + env: ``WORKER_KIND`` picks the worker, ``MCP_URL``
is the coin-data server, ``PUBLIC_URL`` is the worker's advertised A2A URL, ``PORT`` is the
bind port, ``MEMORY_DIR`` is where the worker opens its own checkpointer DB (A4). Adding a
worker = one registry entry here + a compose service.
"""

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import uvicorn
from starlette.applications import Starlette

from crypto_deep_research.contracts.artifact import Dimension
from crypto_deep_research.memory.working import worker_checkpointer, working_db_path
from crypto_deep_research.wiring import DEFAULT_MEMORY_DIR
from crypto_deep_research.workers.market.service import build_market_app
from crypto_deep_research.workers.onchain.service import build_onchain_app
from crypto_deep_research.workers.orderbook.service import build_orderbook_app
from crypto_deep_research.workers.sentiment.service import build_sentiment_app

_BUILDERS: dict[str, Callable[[str, str, Any], Starlette]] = {
    "market": build_market_app,
    "orderbook": build_orderbook_app,
    "sentiment": build_sentiment_app,
    "onchain": build_onchain_app,
}


def build_app(checkpointer: Any = None) -> Starlette:
    builder = _BUILDERS[os.environ["WORKER_KIND"]]
    return builder(os.environ["MCP_URL"], os.environ["PUBLIC_URL"], checkpointer)


if __name__ == "__main__":
    dimension = cast(Dimension, os.environ["WORKER_KIND"])
    memory_dir = os.environ.get("MEMORY_DIR") or DEFAULT_MEMORY_DIR
    Path(memory_dir).mkdir(parents=True, exist_ok=True)
    with worker_checkpointer(working_db_path(memory_dir, dimension)) as cp:
        uvicorn.run(build_app(cp), host="0.0.0.0", port=int(os.environ["PORT"]))
