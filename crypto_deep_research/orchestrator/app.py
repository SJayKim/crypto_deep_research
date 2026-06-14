"""Orchestrator graph (M3): plan -> dispatch -> synthesize over the worker fan-out.

``plan`` discovers the worker registry from Agent Cards and reads long-term memory to pick
the worker set (TENSION-B). ``dispatch`` fans out over A2A with ``asyncio.gather`` (P9).
``synthesize`` merges the artifacts into a ``SynthesisReport`` with per-dimension coverage
(TENSION-C). Orchestrator state holds only distilled artifacts -- never a worker's raw
context (A2).

[한글 설명]
이 파일은 세 단계(plan→dispatch→synthesize)를 LangGraph 선형 그래프로 조립하고, 실행의 수명주기
(메모리 읽기/쓰기)를 관리한다.
- LangGraph의 역할은 "일 나눠주기(fan-out)"가 아니다(그건 P9대로 그래프 바깥 asyncio.gather에서).
  여기서 LangGraph는 단계 사이의 서류철(OrchestratorState) 운반 + 작업 순서도(노드 순서) 명시만 한다.
- 격리(A2): 서류철에는 워커의 요약(WorkerArtifact)/결손 메모(DimensionGap)만 들어가는 칸이 있고,
  원자료가 들어갈 칸은 타입상 아예 없다 — 이 스키마가 격리의 증명서다.
- 메모리 트리거: 읽기는 실행 시작(에피소드/장기), 쓰기는 실행 끝(에피소드/장기). 순서도 내부엔 메모리가 없다.
"""

import time
from typing import Any, TypedDict, cast

from langgraph.graph import END, START, StateGraph

from crypto_deep_research.contracts.artifact import Dimension, WorkerArtifact
from crypto_deep_research.contracts.memory import EpisodicMemory, LongTermMemory, RunRecord
from crypto_deep_research.contracts.report import DimensionGap, SynthesisReport
from crypto_deep_research.orchestrator.dispatch import fan_out
from crypto_deep_research.orchestrator.planner import discover, plan_dimensions
from crypto_deep_research.orchestrator.synthesize import synthesize


# [기능] 단계 사이에 넘겨주는 "서류철"의 정의. 팀장이 실행 중 들고 있을 수 있는 모든 것의 목록.
# [왜] 이 TypedDict가 격리(A2)의 증명서 — results 칸에는 WorkerArtifact | DimensionGap(요약/결손)만 들어가고,
#      워커의 원자료(예: 시세 1000행)가 들어갈 칸이 아예 없다. 격리 테스트가 검사하는 대상이 바로 이 스키마다.
# total=False: 시작 시점엔 plan/results/report가 아직 없으므로 "모든 칸은 비어 있어도 됨"(점진적 채움 패턴).
# longterm(수첩)을 서류철에 실어 운반 → 각 단계가 전역 변수가 아니라 서류철에서 도구를 꺼내 써, 테스트에서 가짜로 바꿔치기 쉬움.
class OrchestratorState(TypedDict, total=False):
    symbol: str
    run_id: str
    worker_urls: list[str]
    longterm: LongTermMemory
    timeout_s: float
    episodic_seed: dict[str, str] | None
    plan: dict[Dimension, str]
    results: list[WorkerArtifact | DimensionGap]
    report: SynthesisReport


# [기능] 계획 단계 = 명함 수집(통신, discover) + 인원 선발(순수 계산, plan_dimensions).
# [왜] 돌려주는 건 새로 끼울 서류 한 장(plan)만 담은 dict — LangGraph 단계의 "내가 바꾼 것만 반환" 규약.
#      마지막 줄에서 선발된 담당만 {담당: 주소}로 좁히므로, 분배 단계는 선발 안 된 워커의 존재 자체를 모른다.
async def _plan(state: OrchestratorState) -> dict[str, Any]:
    registry = await discover(state["worker_urls"])
    chosen = plan_dimensions(state["symbol"], registry, state["longterm"])
    return {"plan": {dimension: registry[dimension] for dimension in chosen}}


# [기능] fan_out을 불러주는 얇은 연결 코드(분배 단계).
# [왜] .get("timeout_s", 30.0): total=False라 칸이 비어 있을 수 있으므로 "없으면 기본값"으로 꺼낸다.
#      반드시 있어야 하는 칸(state["plan"])과 꺼내는 방식이 다른 것 자체가 문서 역할을 한다.
async def _dispatch(state: OrchestratorState) -> dict[str, Any]:
    results = await fan_out(
        state["plan"],
        state["symbol"],
        state["run_id"],
        state.get("timeout_s", 30.0),
        state.get("episodic_seed"),
    )
    return {"results": results}


# [기능] 합성 단계. 유일하게 async가 없는 노드 — synthesize가 기다릴 통신이 전혀 없는 순수 계산이기 때문.
# (LangGraph는 async/동기 노드를 섞어 받아준다.)
def _synthesize(state: OrchestratorState) -> dict[str, Any]:
    return {"report": synthesize(state["symbol"], state["results"])}


# [기능] 작업 순서도(그래프)를 조립한다: 시작→계획→분배→합성→끝, 갈림길 0개.
# [왜] "LangGraph니까 복잡한 그래프"가 아니라 필요한 만큼만 — 흐름이 일직선이라 일직선으로 그렸다(Simplicity First).
#      반환 타입 Any: LangGraph 결과물의 정식 타입 이름이 너무 길어 실용적으로 생략(외부 라이브러리 경계의 흔한 타협).
def build_orchestrator() -> Any:
    graph = StateGraph(OrchestratorState)
    graph.add_node("plan", _plan)
    graph.add_node("dispatch", _dispatch)
    graph.add_node("synthesize", _synthesize)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "dispatch")
    graph.add_edge("dispatch", "synthesize")
    graph.add_edge("synthesize", END)
    return graph.compile()


# [기능] 지난 실행 기록(RunRecord, 보고서 전체 포함)에서 딱 두 조각(실행 ID, 보고서 제목)만 추려 쪽지(seed)로 만든다.
# [왜] "요약본만 주고받는다"는 증류 원칙은 메모리→워커 방향에도 적용된다. 지난 보고서 전문을 4명 업무 지시문에 다 넣으면
#      분량만 부풀고, 워커에겐 "지난번엔 이런 결론이었다"는 한 줄 참조면 충분하다.
def _episodic_seed(prior: RunRecord | None) -> dict[str, str] | None:
    """A compact reference to the last run, passed to workers via ``TaskParams.episodic_seed``."""
    if prior is None:
        return None
    return {"prior_run_id": prior.run_id, "prior_headline": prior.report.headline}


# [기능] 시스템 전체의 정문(진입점). 메모리 읽기 → 그래프 실행 → 메모리 쓰기의 수명주기를 감싼다.
# [왜] episodic(회의록)이 Optional인 건 회의록 없이도 돌아야 하기 때문(테스트/초기 마일스톤 호환).
#      반면 longterm(수첩)은 필수 — 플래너가 수첩 없이는 계획을 못 세운다. 의도된 비대칭.
async def run_orchestrator(
    symbol: str,
    run_id: str,
    worker_urls: list[str],
    longterm: LongTermMemory,
    timeout_s: float = 30.0,
    episodic: EpisodicMemory | None = None,
) -> SynthesisReport:
    # [에피소드 메모리 READ 트리거] 실행 시작에 이 코인의 가장 최근 실행을 읽어 워커 디스패치용 쪽지(seed)로 만든다.
    # Run start: read the last run for this symbol and seed it into the worker dispatch.
    seed = _episodic_seed(episodic.last_for(symbol)) if episodic is not None else None
    # 초기 서류철을 넣고 순서도를 끝까지 비동기 실행(ainvoke). 호출마다 그래프를 새로 조립한다
    # (재사용 캐싱은 실측으로 필요가 확인되기 전까지 안 함).
    final = await build_orchestrator().ainvoke(
        {
            "symbol": symbol,
            "run_id": run_id,
            "worker_urls": worker_urls,
            "longterm": longterm,
            "timeout_s": timeout_s,
            "episodic_seed": seed,
        }
    )
    # cast: 실행 결과가 느슨한 dict라, mypy에게 "이 칸은 SynthesisReport 맞다"고 알려주는 표기(실행 중 검사 아님).
    report = cast(SynthesisReport, final["report"])
    # [메모리 WRITE 트리거] 실행 끝에 둘 다 쓴다 — 에피소드: 이번 실행을 회의록으로 보관 / 장기: 새로 배운 사실을 수첩에 추가.
    # 읽기는 시작, 쓰기는 끝 — 메모리를 만지는 지점이 실행의 양 끝에만 있고 순서도 내부엔 없다(A4: 팀장만이 에피소드/장기 DB를 소유).
    # Run end: store this run (episodic) and append what it learned (long-term).
    if episodic is not None:
        episodic.put(RunRecord(run_id=run_id, symbol=symbol, ts=int(time.time()), report=report))
    # add_facts: 리뷰 O2 지적 지점 — 무조건 적으면 같은 내용이 무한 중복으로 쌓여 수첩이 잡동사니가 된다(신호 퇴화).
    # 방어(중복 제거/개수 상한)는 수첩 구현부와 플래너의 단어 매칭에 두고, 호출하는 이 줄은 단순하게 유지.
    longterm.add_facts(symbol, report.key_points)
    return report
