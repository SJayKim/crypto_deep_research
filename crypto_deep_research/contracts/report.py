"""SynthesisReport: the orchestrator's merged output with per-dimension coverage (TENSION-C).

[한글 설명]
오케스트레이터(팀장)가 워커 4장의 보고서를 종합해 내는 "최종 합성 보고서" 양식.
핵심은 TENSION-C: 워커 1명이 타임아웃돼도 보고서는 나와야 하지만, 그게 멀쩡한
완성본처럼 보이면 읽는 사람이 "4개 차원을 다 본 분석"으로 오해한다. 그래서 최종
보고서는 차원별 커버리지(무엇을 봤고 무엇을 못 봤는지)를 "명시적인 칸"으로 운반해,
부분 실패가 보고서에 눈에 보이게 남도록 한다(A3 "조용한 실패 금지"의 부분 실패 버전).
"""

from typing import Literal

from pydantic import BaseModel, Field

from crypto_deep_research.contracts.artifact import Dimension, Evidence


# "빠진 차원 신고 양식": 어느 차원이 왜 빠졌나.
# reason이 자유 문자열인 건 사람이 읽을 진단 메모이기 때문 — 프로그램이 이 값으로
# 동작을 분기하지 않으므로 Literal로 닫지 않는다.
class DimensionGap(BaseModel):
    dimension: Dimension
    reason: str  # e.g. "timeout", "mcp_down"


# 팀장이 4장의 보고서를 종합해 내는 "최종 보고서 양식".
class SynthesisReport(BaseModel):
    symbol: str
    # 워커의 2값(ok|failed)과 달리 3값: 종합 단계에만 존재하는 partial이 추가된다.
    # 4/4 성공=ok, 1~3/4=partial, 0/4=failed.
    status: Literal["ok", "partial", "failed"]
    headline: str = Field(max_length=200)
    # 워커(5개)의 두 배인 10개 — 4개 차원을 합치는 보고서라 상한이 더 크지만, 여전히 상한이 있다
    # (증류 원칙은 종합 단계에도 적용).
    key_points: list[str] = Field(max_length=10)
    evidence: list[Evidence] = Field(default_factory=list)
    # dimensions_ok + dimensions_unavailable를 합치면 항상 4개 차원 전체가 되도록 하는 게 의도.
    # 보고서만 봐도 "무엇을 근거로 했고 무엇이 빠졌는지"가 자기완결적으로 드러난다.
    # Dimension/Evidence를 artifact.py에서 재사용 → 워커 근거가 양식 변환 없이 그대로 흘러간다.
    dimensions_ok: list[Dimension]
    dimensions_unavailable: list[DimensionGap]  # TENSION-C
