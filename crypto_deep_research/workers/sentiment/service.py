"""A2A service for the sentiment worker: the shared harness + its Agent Card.

[한글 설명] market의 service.py와 구조 100% 동일. 명함의 name/description/skills 문구만 다르다.
partial(..., checkpointer=...) 주입도 동일(W2/A4).
"""

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
