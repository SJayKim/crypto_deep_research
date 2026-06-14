"""A2A service for the onchain worker: the shared harness + its Agent Card.

[한글 설명] market의 service.py와 구조 100% 동일. 명함 문구만 다르다. 4개 service.py가 판박이라는
사실 자체가 C6(공용 틀 추출)의 성과 지표다.
"""

from functools import partial
from typing import Any

from starlette.applications import Starlette

from crypto_deep_research.contracts.a2a import AgentCard
from crypto_deep_research.workers.base import build_worker_app
from crypto_deep_research.workers.onchain.agent import analyze_onchain


def build_onchain_app(mcp_url: str, public_url: str, checkpointer: Any = None) -> Starlette:
    card = AgentCard(
        name="onchain-worker",
        description="On-chain activity (active addresses, exchange netflow) as a WorkerArtifact.",
        url=public_url,
        version="0.1.0",
        skills=["analyze:onchain"],
    )
    return build_worker_app(card, partial(analyze_onchain, checkpointer=checkpointer), mcp_url)
