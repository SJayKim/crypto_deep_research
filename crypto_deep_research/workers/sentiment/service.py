"""A2A service for the sentiment worker: the shared harness + its Agent Card."""

from functools import partial
from typing import Any

from starlette.applications import Starlette

from crypto_deep_research.contracts.a2a import AgentCard
from crypto_deep_research.workers.base import build_worker_app
from crypto_deep_research.workers.sentiment.agent import analyze_sentiment


def build_sentiment_app(mcp_url: str, public_url: str, checkpointer: Any = None) -> Starlette:
    card = AgentCard(
        name="sentiment-worker",
        description="Crypto news sentiment (net tone, source-weighted) as a WorkerArtifact.",
        url=public_url,
        version="0.1.0",
        skills=["analyze:sentiment"],
    )
    return build_worker_app(card, partial(analyze_sentiment, checkpointer=checkpointer), mcp_url)
