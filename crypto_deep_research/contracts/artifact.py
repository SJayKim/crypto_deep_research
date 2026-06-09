"""WorkerArtifact: the distilled, bounded output every worker emits (A2)."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Dimension = Literal["market", "orderbook", "sentiment", "onchain"]


class Evidence(BaseModel):
    metric: str = Field(max_length=64)  # e.g. "RSI_14"
    value: float | str  # self-contained; never a pointer into worker context


class WorkerArtifact(BaseModel):
    dimension: Dimension
    status: Literal["ok", "failed"]
    headline: str = Field(max_length=200)
    key_points: list[str] = Field(max_length=5)  # <=5 points (A2)
    evidence: list[Evidence] = Field(default_factory=list, max_length=10)

    @field_validator("key_points")
    @classmethod
    def _cap_point_len(cls, v: list[str]) -> list[str]:  # each point <=200 chars
        if any(len(p) > 200 for p in v):
            raise ValueError("key_point exceeds 200 chars")
        return v
