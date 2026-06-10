"""Planner: discover the available workers, then pick the worker set from long-term memory.

``discover`` reads each worker's Agent Card (``GET /.well-known/agent.json``) and maps its
declared skill to a ``Dimension`` -- a data-driven registry, so adding a worker is one env
URL, never an orchestrator edit (AC#7). ``plan_dimensions`` is the long-term READ trigger
(TENSION-B): ``market`` is always analyzed; every other dimension is included only when the
symbol is on the long-term watchlist or a stored fact names it.
"""

import asyncio
import re

import httpx

from crypto_deep_research.contracts.a2a import AgentCard
from crypto_deep_research.contracts.artifact import Dimension
from crypto_deep_research.contracts.memory import LongTermMemory

_DIMENSIONS: tuple[Dimension, ...] = ("market", "orderbook", "sentiment", "onchain")


def _skill_dimension(card: AgentCard) -> Dimension | None:
    for dimension in _DIMENSIONS:
        if f"analyze:{dimension}" in card.skills:
            return dimension
    return None


async def _fetch_card(worker_url: str) -> AgentCard:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(f"{worker_url}/.well-known/agent.json")
    return AgentCard.model_validate(response.json())


async def discover(worker_urls: list[str]) -> dict[Dimension, str]:
    """Map each worker URL to its dimension via its Agent Card (data-driven registry)."""
    cards = await asyncio.gather(*[_fetch_card(url) for url in worker_urls])
    registry: dict[Dimension, str] = {}
    for url, card in zip(worker_urls, cards, strict=True):
        dimension = _skill_dimension(card)
        if dimension is not None:
            registry[dimension] = url
    return registry


def plan_dimensions(
    symbol: str, registry: dict[Dimension, str], longterm: LongTermMemory
) -> list[Dimension]:
    """Long-term READ: market always; others iff watchlisted or named by a stored fact."""
    chosen: set[Dimension] = set()
    if "market" in registry:
        chosen.add("market")
    watched = symbol in longterm.watchlist()
    fact_tokens = set(re.findall(r"[a-z0-9]+", " ".join(longterm.facts(symbol)).lower()))
    for dimension in registry:
        if dimension == "market":
            continue
        if watched or dimension in fact_tokens:
            chosen.add(dimension)
    return [d for d in _DIMENSIONS if d in chosen]
