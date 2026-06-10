"""A2A service for the orderbook worker: the shared harness + its Agent Card."""

from functools import partial
from typing import Any

from starlette.applications import Starlette

from crypto_deep_research.contracts.a2a import AgentCard
from crypto_deep_research.workers.base import build_worker_app
from crypto_deep_research.workers.orderbook.agent import analyze_orderbook


def build_orderbook_app(mcp_url: str, public_url: str, checkpointer: Any = None) -> Starlette:
    card = AgentCard(
        name="orderbook-worker",
        description="Order-book microstructure (spread, depth imbalance) as a WorkerArtifact.",
        url=public_url,
        version="0.1.0",
        skills=["analyze:orderbook"],
    )
    return build_worker_app(card, partial(analyze_orderbook, checkpointer=checkpointer), mcp_url)
