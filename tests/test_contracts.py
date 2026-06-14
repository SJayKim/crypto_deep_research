"""M0 contract validators + report round-trip. Deterministic, no LLM (T7b).

[한글 설명] 6개 서비스가 공유하는 타입 계약(contracts)의 검증. ARCHITECTURE-MAP §7의
"M0 계약 스키마"에 해당한다. 핵심은 결정코드 A2(증류 경계 강제): WorkerArtifact는
Pydantic validator로 "key_points ≤ 5개, 길이 캡" 등 bounded 필드를 강제해야 한다.
즉 워커가 raw 데이터를 그대로 흘려보내지 못하게 타입 차원에서 막는 게 Distillation의 토대.
또 SynthesisReport가 ok/partial/failed 상태와 커버리지(gap)를 손실 없이 직렬화/역직렬화하는지 확인한다.
"""

from typing import Literal

import pytest
from pydantic import ValidationError

from crypto_deep_research.contracts.artifact import Evidence, WorkerArtifact
from crypto_deep_research.contracts.report import DimensionGap, SynthesisReport


# key_points 6개는 거부되어야 한다. A2 증류 경계("≤5개")를 타입이 강제하는지 검증.
def test_worker_artifact_rejects_six_key_points() -> None:
    with pytest.raises(ValidationError):
        WorkerArtifact(
            dimension="market",
            status="ok",
            headline="ok",
            key_points=[f"point {i}" for i in range(6)],
        )


# 너무 긴 key_point(201자)는 거부. A2 "길이 캡"으로 워커가 raw 텍스트를 통째로 못 넣게 막음.
def test_worker_artifact_rejects_overlong_key_point() -> None:
    with pytest.raises(ValidationError):
        WorkerArtifact(
            dimension="market",
            status="ok",
            headline="ok",
            key_points=["x" * 201],
        )


# headline도 길이 캡 적용(201자 거부). 증류 결과는 짧아야 한다는 A2 경계 검증.
def test_worker_artifact_rejects_overlong_headline() -> None:
    with pytest.raises(ValidationError):
        WorkerArtifact(
            dimension="market",
            status="ok",
            headline="h" * 201,
            key_points=["ok"],
        )


# 경계 안(200자 ×5개 + evidence)은 통과해야 한다. validator가 정상 입력까지 막지 않는지 확인.
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


# 최종 리포트가 3가지 상태(ok/partial/failed)와 커버리지(dimensions_ok / gap+reason)를
# JSON 왕복 후에도 동일하게 보존하는지. TENSION-C("부분 실패를 가시화")의 타입 토대.
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
