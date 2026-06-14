"""Layered-memory protocols + RunRecord (working / episodic / long-term).

[한글 설명]
3층 메모리(작업/에피소드/장기)의 인터페이스를 정의한 파일.
다른 contracts와 달리 여기 세 메모리 클래스는 "데이터의 모양"이 아니라
"행위(할 수 있는 일의 목록)의 계약"이라 Pydantic이 아닌 typing.Protocol을 쓴다.
Protocol = "이 메서드들을 가진 객체면 무엇이든 통과"라는 직무기술서(구조적 타이핑).
덕분에 구현(SQLite로 저장하든 메모리 임시 저장하든)을 계약에서 분리해, 테스트에서
가짜 구현으로 갈아끼우기 쉽다. 3층 구조는 에이전트 메모리의 표준 분류를 따른다:
작업(실행 1회)=책상 위 메모, 에피소드(실행 간·심볼별)=업무 일지, 장기(영구)=지식 노트.
"""

from typing import Protocol

from pydantic import BaseModel

from crypto_deep_research.contracts.report import SynthesisReport


# 에피소드 메모리(업무 일지)에 저장되는 한 페이지 = "한 번의 실행 기록".
# 최종 보고서를 통째로 담으며, 다음 실행에서 episodic_seed(a2a.py)로 동봉할 요약의 원재료가 된다.
# 이건 행위가 아니라 데이터(서류)라서 Protocol이 아닌 BaseModel.
class RunRecord(BaseModel):
    run_id: str
    symbol: str
    ts: int  # 타임스탬프
    report: SynthesisReport


# 작업 메모리의 직무기술서. 단, 솔직한 역사적 흔적:
# M0에서 계약을 먼저 정의했으나, 실제로는 LangGraph의 checkpointer + 그래프 상태가
# 작업 메모리 역할을 대신하게 됐다. 그래서 이 Protocol을 수행하는 구현체는 없다(orphan).
# 코드 리뷰에서 발견(C2)됐지만 지우는 대신 docstring으로 사실을 기록 — M0 계약의 형태 보존도 학습 가치.
class WorkingMemory(Protocol):
    """구현은 checkpointer(``memory/working.py``)로 대체 — note/read는 미사용 (C2)."""

    # Protocol 메서드 끝의 ...는 "이런 일을 할 수 있어야 한다"는 항목만 적고 본문은 없다는 관례 표기.
    def note(self, run_id: str, key: str, value: str) -> None: ...  # write: worker records notes
    def read(self, run_id: str) -> dict[str, str]: ...  # read: distill node


# 에피소드 메모리(업무 일지)의 직무기술서: "마지막 기록 꺼내기" + "새 기록 넣기" 딱 두 가지.
# 인터페이스가 의도적으로 좁다 — 마지막 기록 하나만 읽고(last_for), 전체 이력 검색은 v1에 없다.
# 주석이 읽기/쓰기 시점을 명시: 누가 언제 부르는지도 계약의 일부(읽기=실행 시작, 쓰기=실행 끝, 팀장만 접근).
class EpisodicMemory(Protocol):
    def last_for(self, symbol: str) -> RunRecord | None: ...  # read: run start  # None=그 코인 첫 실행
    def put(self, record: RunRecord) -> None: ...  # write: run end


# 장기 지식 노트의 직무기술서. watchlist=추적 중인 코인 목록, facts=코인별 누적 사실.
# 플래너(실행 계획 수립부)가 읽고, 실행이 끝나면 새로 알게 된 사실을 추가한다.
# add_facts(추가)만 있고 삭제/수정이 없다 — append-only(덧붙이기만 가능). 필요해질 때까지 안 만든다.
class LongTermMemory(Protocol):
    def watchlist(self) -> list[str]: ...  # read: planner
    def facts(self, symbol: str) -> list[str]: ...  # read: planner
    def add_facts(self, symbol: str, facts: list[str]) -> None: ...  # write: run end
