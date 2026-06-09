"""Process entry for one worker: ``python -m crypto_deep_research.serve_worker``.

Lives outside ``workers/`` on purpose: it's packaging, not agent code, so the M5 live
swap leaves ``workers/`` and ``orchestrator/`` byte-for-byte unchanged (AC#2). Env-driven
so a worker container is just an image + env: ``WORKER_KIND`` picks the worker, ``MCP_URL``
is the coin-data server, ``PUBLIC_URL`` is the worker's advertised A2A URL, ``PORT`` is the
bind port. Adding a worker = one registry entry here + a compose service.
"""

import os
from collections.abc import Callable

import uvicorn
from starlette.applications import Starlette

from crypto_deep_research.workers.market.service import build_market_app
from crypto_deep_research.workers.onchain.service import build_onchain_app
from crypto_deep_research.workers.orderbook.service import build_orderbook_app
from crypto_deep_research.workers.sentiment.service import build_sentiment_app

_BUILDERS: dict[str, Callable[[str, str], Starlette]] = {
    "market": build_market_app,
    "orderbook": build_orderbook_app,
    "sentiment": build_sentiment_app,
    "onchain": build_onchain_app,
}


def build_app() -> Starlette:
    builder = _BUILDERS[os.environ["WORKER_KIND"]]
    return builder(os.environ["MCP_URL"], os.environ["PUBLIC_URL"])


if __name__ == "__main__":
    uvicorn.run(build_app(), host="0.0.0.0", port=int(os.environ["PORT"]))
