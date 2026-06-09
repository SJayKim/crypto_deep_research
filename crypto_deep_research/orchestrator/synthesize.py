"""Synthesizer: merge worker artifacts into a SynthesisReport with per-dimension coverage.

Three result kinds arrive from the fan-out: an ``ok`` artifact (contributes to the
report), a ``failed`` artifact (worker reached but its source was down -> a gap), and a
``DimensionGap`` (worker timed out or was unreachable). The report makes coverage explicit
(TENSION-C): ``dimensions_ok`` lists what was analyzed, ``dimensions_unavailable`` lists
each missing dimension with a reason. Status is ``ok`` (all covered), ``partial`` (some),
or ``failed`` (none) -- never a silent gap (A3).
"""

from typing import Literal

from crypto_deep_research.contracts.artifact import WorkerArtifact
from crypto_deep_research.contracts.report import DimensionGap, SynthesisReport


def _gaps(results: list[WorkerArtifact | DimensionGap]) -> list[DimensionGap]:
    gaps = [r for r in results if isinstance(r, DimensionGap)]
    for r in results:
        if isinstance(r, WorkerArtifact) and r.status == "failed":
            reason = r.key_points[0] if r.key_points else "worker reported failure"
            gaps.append(DimensionGap(dimension=r.dimension, reason=reason))
    return gaps


def _status(
    ok: list[WorkerArtifact], gaps: list[DimensionGap]
) -> Literal["ok", "partial", "failed"]:
    if not ok:
        return "failed"
    return "partial" if gaps else "ok"


def synthesize(symbol: str, results: list[WorkerArtifact | DimensionGap]) -> SynthesisReport:
    ok = [r for r in results if isinstance(r, WorkerArtifact) and r.status == "ok"]
    gaps = _gaps(results)
    headline = f"{symbol}: {len(ok)}/{len(ok) + len(gaps)} dimensions covered"
    return SynthesisReport(
        symbol=symbol,
        status=_status(ok, gaps),
        headline=headline[:200],
        key_points=[point for artifact in ok for point in artifact.key_points][:10],
        evidence=[item for artifact in ok for item in artifact.evidence],
        dimensions_ok=[artifact.dimension for artifact in ok],
        dimensions_unavailable=gaps,
    )
