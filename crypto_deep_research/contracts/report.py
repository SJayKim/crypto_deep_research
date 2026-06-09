"""SynthesisReport: the orchestrator's merged output with per-dimension coverage (TENSION-C)."""

from typing import Literal

from pydantic import BaseModel, Field

from crypto_deep_research.contracts.artifact import Dimension, Evidence


class DimensionGap(BaseModel):
    dimension: Dimension
    reason: str  # e.g. "timeout", "mcp_down"


class SynthesisReport(BaseModel):
    symbol: str
    status: Literal["ok", "partial", "failed"]
    headline: str = Field(max_length=200)
    key_points: list[str] = Field(max_length=10)
    evidence: list[Evidence] = Field(default_factory=list)
    dimensions_ok: list[Dimension]
    dimensions_unavailable: list[DimensionGap]  # TENSION-C
