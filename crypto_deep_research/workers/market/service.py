"""A2A service for the market worker: the shared harness + the market Agent Card."""

from functools import partial
from typing import Any

from starlette.applications import Starlette

from crypto_deep_research.contracts.a2a import AgentCard
from crypto_deep_research.workers.base import build_worker_app
from crypto_deep_research.workers.market.agent import analyze_market


def build_market_app(mcp_url: str, public_url: str, checkpointer: Any = None) -> Starlette:
    card = AgentCard(
        name="market-worker",
        description="Crypto market analysis (OHLCV trend/momentum) as a WorkerArtifact.",
        url=public_url,
        version="0.1.0",
        skills=["analyze:market"],
    )
    return build_worker_app(card, partial(analyze_market, checkpointer=checkpointer), mcp_url)
