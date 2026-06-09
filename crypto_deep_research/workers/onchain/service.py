"""A2A service for the onchain worker: the shared harness + its Agent Card."""

from starlette.applications import Starlette

from crypto_deep_research.contracts.a2a import AgentCard
from crypto_deep_research.workers.base import build_worker_app
from crypto_deep_research.workers.onchain.agent import analyze_onchain


def build_onchain_app(mcp_url: str, public_url: str) -> Starlette:
    card = AgentCard(
        name="onchain-worker",
        description="On-chain activity (active addresses, exchange netflow) as a WorkerArtifact.",
        url=public_url,
        version="0.1.0",
        skills=["analyze:onchain"],
    )
    return build_worker_app(card, analyze_onchain, mcp_url)
