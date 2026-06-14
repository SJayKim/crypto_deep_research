"""Synthesizer: merge worker artifacts into a SynthesisReport with per-dimension coverage.

Three result kinds arrive from the fan-out: an ``ok`` artifact (contributes to the
report), a ``failed`` artifact (worker reached but its source was down -> a gap), and a
``DimensionGap`` (worker timed out or was unreachable). The report makes coverage explicit
(TENSION-C): ``dimensions_ok`` lists what was analyzed, ``dimensions_unavailable`` lists
each missing dimension with a reason. Status is ``ok`` (all covered), ``partial`` (some),
or ``failed`` (none) -- never a silent gap (A3).

[한글 설명]
이 파일은 "팀원들이 보낸 요약을 하나의 최종 보고서로 묶는" 합성(synthesize) 단계다. 핵심은 TENSION-C —
1/4만 성공한 실행도 눈에 보이게 partial이어야 한다. 합성기의 일은 단순 이어붙이기가 아니라 회계다:
무엇이 들어왔고(dimensions_ok) 무엇이 빠졌는지(dimensions_unavailable)를 빠짐없이 장부에 남긴다.
fan-out에서 도착하는 결과는 세 종류:
  1) status="ok" artifact — 일을 잘 끝낸 보고 → 보고서에 기여
  2) status="failed" artifact — 워커와 연락은 됐지만 스스로 "자료 출처(MCP)가 죽었어요"라고 보고 → gap으로 번역
  3) DimensionGap — 워커에게 아예 연락이 안 닿음(시간 초과/접속 불가)
2와 3은 다른 종류의 실패다("살아서 못 했다고 말함" vs "응답 없음").
순수 함수(통신·저장 없음)라 partial/zero 테스트가 가짜 목록만으로 돈다.
"""

from typing import Literal

from crypto_deep_research.contracts.artifact import WorkerArtifact
from crypto_deep_research.contracts.report import DimensionGap, SynthesisReport


# [기능] 결손 목록을 모은다: 종류 3(연락 두절 메모)은 그대로 수집, 종류 2(자가 보고 실패)는 gap으로 번역.
# [왜] 실패한 워커 보고는 "왜 실패했는지"를 key_points 첫 줄에 적는다는 암묵적 약속이 있어 그걸 실패 이유로 채택.
#      isinstance 분기는 두 종류(둘 다 Pydantic 모델)가 섞인 목록을 다루는 정직한 방법.
def _gaps(results: list[WorkerArtifact | DimensionGap]) -> list[DimensionGap]:
    gaps = [r for r in results if isinstance(r, DimensionGap)]
    for r in results:
        if isinstance(r, WorkerArtifact) and r.status == "failed":
            reason = r.key_points[0] if r.key_points else "worker reported failure"
            gaps.append(DimensionGap(dimension=r.dimension, reason=reason))
    return gaps


# [기능] 최종 보고서의 3단계 상태를 정한다. 워커는 2단계(ok/failed), 합성은 여기서 partial을 새로 만든다.
# [왜] 성공 0건이면 failed(A3의 zero-artifact 경로 — CLI가 받아 "비정상 종료" 신호로 변환),
#      결손이 하나라도 있으면 partial(부분 성공), 아니면 ok. 절대 조용히 넘어가는 gap은 없다.
def _status(
    ok: list[WorkerArtifact], gaps: list[DimensionGap]
) -> Literal["ok", "partial", "failed"]:
    if not ok:
        return "failed"
    return "partial" if gaps else "ok"


# [기능] 결과 목록을 받아 커버리지가 명시된 SynthesisReport 한 장을 만든다(TENSION-C의 본체).
# [왜] 모든 결과를 "성공" 아니면 "결손"으로 정확히 한 번씩 분류하므로, 두 칸의 합은 항상 계획 전체와 같다.
def synthesize(symbol: str, results: list[WorkerArtifact | DimensionGap]) -> SynthesisReport:
    ok = [r for r in results if isinstance(r, WorkerArtifact) and r.status == "ok"]
    gaps = _gaps(results)
    # 제목이 곧 커버리지 선언: "BTC: 3/4 dimensions covered". 분모 len(ok)+len(gaps)는 계획 항목 수와 같다
    # (계획표를 따로 안 넘겨받아도 장부가 맞아떨어짐). 보고서 첫 줄부터 부분 실패가 보인다(visibly marked).
    headline = f"{symbol}: {len(ok)}/{len(ok) + len(gaps)} dimensions covered"
    return SynthesisReport(
        symbol=symbol,
        status=_status(ok, gaps),
        # headline[:200]: 양식 상한(200자)을 넘으면 Pydantic 검사에 걸려 보고서 생성이 죽으므로 미리 자르는 방어.
        headline=headline[:200],
        # 성공 보고들의 요점을 담당 순서대로 이어붙이고 10개에서 자른다(워커당 5개 × 합성 후 10개).
        # 현재는 AI 재서술이 아니라 기계적 이어붙이기 — 진짜 "요점 재서술"은 Approach C(critic/compressor)로 의도적으로 미뤄둠.
        key_points=[point for artifact in ok for point in artifact.key_points][:10],
        # evidence(근거 자료)에는 자르기가 없다 — 양식에 상한이 없어 통과는 되나, 리뷰 03이 "증거 폭주 방지 [:N]
        # 슬라이스 도입 여부"를 미결정(C1 연계 열린 항목)으로 남겨둔 상태.
        evidence=[item for artifact in ok for item in artifact.evidence],
        # TENSION-C가 요구한 두 칸: "된 항목 목록"과 "안 된 항목 목록(이유 포함)".
        dimensions_ok=[artifact.dimension for artifact in ok],
        dimensions_unavailable=gaps,
    )
