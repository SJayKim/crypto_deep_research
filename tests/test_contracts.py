"""M0 contract validators + report round-trip. Deterministic, no LLM (T7b)."""

from typing import Literal

import pytest
from pydantic import ValidationError

from crypto_deep_research.contracts.artifact import Evidence, WorkerArtifact
from crypto_deep_research.contracts.report import DimensionGap, SynthesisReport


def test_worker_artifact_rejects_six_key_points() -> None:
    with pytest.raises(ValidationError):
        WorkerArtifact(
            dimension="market",
            status="ok",
            headline="ok",
            key_points=[f"point {i}" for i in range(6)],
        )


def test_worker_artifact_rejects_overlong_key_point() -> None:
    with pytest.raises(ValidationError):
        WorkerArtifact(
            dimension="market",
            status="ok",
            headline="ok",
            key_points=["x" * 201],
        )


def test_worker_artifact_rejects_overlong_headline() -> None:
    with pytest.raises(ValidationError):
        WorkerArtifact(
            dimension="market",
            status="ok",
            headline="h" * 201,
            key_points=["ok"],
        )


def test_worker_artifact_accepts_bounds() -> None:
    artifact = WorkerArtifact(
        dimension="market",
        status="ok",
        headline="h" * 200,
        key_points=["p" * 200] * 5,
        evidence=[Evidence(metric="RSI_14", value=55.0)],
    )
    assert artifact.dimension == "market"
    assert len(artifact.key_points) == 5


@pytest.mark.parametrize("status", ["ok", "partial", "failed"])
def test_synthesis_report_round_trips_status(status: Literal["ok", "partial", "failed"]) -> None:
    report = SynthesisReport(
        symbol="BTC",
        status=status,
        headline="BTC analysis",
        key_points=["uptrend intact"],
        dimensions_ok=["market"],
        dimensions_unavailable=[DimensionGap(dimension="orderbook", reason="timeout")],
    )
    restored = SynthesisReport.model_validate_json(report.model_dump_json())
    assert restored == report
    assert restored.status == status
    assert restored.dimensions_ok == ["market"]
    assert restored.dimensions_unavailable[0].reason == "timeout"
