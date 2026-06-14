"""WorkerArtifact: the distilled, bounded output every worker emits (A2).

[한글 설명]
이 파일이 contracts의 심장이다. 설계 결정 A2(증류 강제)를 코드로 구현한 곳.
워커는 OHLCV 1000행 같은 대량 원시 데이터를 받아 분석하지만, 팀장(오케스트레이터)에게는
"분량 상한이 박힌 요약물(증류물)"만 돌려줄 수 있다. "요약해줘"라고 말로 부탁하는 대신,
보고서 양식의 칸 자체를 작게 만들어서 요약이 아니면 Pydantic 검증을 물리적으로
통과할 수 없게 만들었다 (LLM에게 부탁 < 스키마로 강제 — 이 프로젝트의 핵심 교훈).
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

# 분석 차원은 이 4가지 말고는 존재하지 않는다는 "닫힌 집합".
# 아무 글자나 받는 str이 아니라 Literal을 쓴 이유: 오타("markets")가 도착 시점
# 검증과 사전 mypy 검토 양쪽에서 즉시 잡힌다. 워커가 4개로 고정이므로 자유 기입란일 이유가 없다.
Dimension = Literal["market", "orderbook", "sentiment", "onchain"]


# "주장의 근거"를 {지표명, 값} 쌍으로 구조화한 양식. 예: {"metric": "RSI_14", "value": 71.3}.
# 자유 텍스트가 아니라 정해진 칸 두 개인 이유: 종합 단계에서 여러 담당자의 근거를
# 기계적으로 합치고 표로 보여줄 수 있어야 하기 때문(자유 서술이면 사람이 일일이 읽어야 함).
class Evidence(BaseModel):
    metric: str = Field(max_length=64)  # e.g. "RSI_14"
    # value는 그 자체로 완결돼야 한다 — "내 자료의 532번 항목 참조" 같은 포인터 금지.
    # 오케스트레이터는 워커의 메모리를 읽을 수 없으므로(따로 도는 프로그램이라) 값이 자기완결적이어야 한다.
    value: float | str  # self-contained; never a pointer into worker context


# 워커가 제출하는 "분석 결과 보고서 양식". 칸마다 분량 상한이 박혀 있어
# 보고서 전체 크기가 수 KB로 수렴하도록 보장된다(A2의 bounded 약속).
class WorkerArtifact(BaseModel):
    dimension: Dimension  # 이 결과물이 어느 분석 차원 것인지 — 팀장이 4장을 모을 때의 이름표
    # 워커 스스로 적는 성공/실패 표시. 실패해도 보고서는 제출된다(에러를 던지며 자리를 비우지 않음).
    # 부분 실패도 데이터로 다루기 위함 — report.py의 TENSION-C와 연결된다.
    status: Literal["ok", "failed"]
    headline: str = Field(max_length=200)  # 한 줄 결론, 200자 상한
    key_points: list[str] = Field(max_length=5)  # <=5 points (A2)  # 항목 "개수" 상한(글자 수 아님)
    # 근거 최대 10개. default_factory=list인 이유: 빈 리스트 []를 기본값으로 직접 쓰면
    # 모든 인스턴스가 같은 리스트 하나를 공유하는 고전적 함정이 생기는데, 그 표준 회피법이다.
    evidence: list[Evidence] = Field(default_factory=list, max_length=10)

    # 핵심 포인트 한 줄 한 줄도 각각 200자를 넘으면 퇴짜 놓는 추가 검사기.
    # 왜 따로 필요한가? 위 Field(max_length=5)는 "개수"만 제한하고 항목 각각의 "글자 수"는 못 잡는다.
    # 이게 없으면 "포인트는 5개지만 하나에 10만 자"로 양식을 우회할 수 있어, 그 구멍을 막는다.
    @field_validator("key_points")
    @classmethod
    def _cap_point_len(cls, v: list[str]) -> list[str]:  # each point <=200 chars
        if any(len(p) > 200 for p in v):
            raise ValueError("key_point exceeds 200 chars")
        return v
