"""Shared worker harness (C6): the A2A service + the ``data -> work`` graph skeleton.

Extracted after the 2nd worker (rule of three). Every worker is a LangGraph
``data -> work`` agent over the MCP boundary: ``data`` fetches its source via MCP and
``work`` distills it into a bounded ``WorkerArtifact`` (A2). An unreachable MCP server
short-circuits to ``status="failed"`` without ever touching the LLM (A3). LLM workers
(market, sentiment) build their artifact with ``llm_distill``; deterministic workers
(orderbook, onchain) compute it directly.

[한글 설명]
4개 워커(market/sentiment/orderbook/onchain)가 공통으로 끼우는 "공용 틀(하니스)"이다.
- 무슨 기능: A2A 접수 창구 + "data → work" 작업 순서도 골격을 제공한다. 각 워커는
  fetch(자료 가져오기)/work(분석하기) 두 함수만 채우면 된다.
- 왜 이렇게: 처음부터 공용 틀을 만들지 않고, 2번째 워커를 만든 뒤에야 추출했다(C6,
  rule of three). 두 채를 실제로 지어봐야 진짜 공통부와 가변부가 눈에 보이기 때문이다.
- 핵심 원칙: 본부로 넘기는 것은 한도가 정해진 요약 보고서(WorkerArtifact)뿐(A2),
  자료실(MCP)이 죽으면 예외를 던지지 않고 status="failed"로 빠지며 LLM도 안 부른다(A3).
"""

import asyncio
from collections.abc import Callable
from typing import Any, TypedDict, cast

from langchain_anthropic import ChatAnthropic
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from crypto_deep_research.contracts.a2a import (
    AgentCard,
    JsonRpcError,
    JsonRpcRequest,
    JsonRpcResponse,
)
from crypto_deep_research.contracts.artifact import Dimension, Evidence, WorkerArtifact

# _MODEL: LLM 워커 2종(market/sentiment)이 공유하는 인공지능 모델 이름표.
# "어느 AI를 부를지"를 한 곳에 한 줄로만 적어둔다. 환경설정 파일로 빼는 등의 설정화는
# 아무도 요청하지 않아 하지 않았다(Simplicity First — 필요해질 때 하면 된다).
_MODEL = "claude-sonnet-4-6"


# _Distilled: LLM의 답변을 일단 받아두는 임시 그릇(중간 스키마).
# 최종 양식 WorkerArtifact와 닮았지만 글자 수 제한(max_length)이 없는 느슨한 버전이다.
# 왜 WorkerArtifact를 직접 안 쓰나: 최종 양식은 "제목 200자 이내" 같은 엄격한 검사가 붙어
# LLM이 201자를 내놓으면 워커 전체가 실패한다. 느슨한 그릇으로 일단 받은 뒤 아래
# llm_distill에서 코드가 직접 가위질([:200]/[:5]/[:10])해 최종 양식에 옮긴다(A2:
# "LLM이 규칙을 지켜주길 기대하지 말고 코드로 보장한다").
# 이름 앞 _ : 모듈 내부용 표시 — 시스템 간 통신 규약이 아니라 contracts에 두지 않는다.
class _Distilled(BaseModel):
    headline: str
    key_points: list[str]
    evidence: list[Evidence]


# llm_distill: LLM 워커 2종이 공유하는 증류 함수. AI를 2번 불러 "추론 후 압축"한다.
# 왜 2번 부르나: 리뷰(W5)가 비용을 지적했으나, '생각하기'와 '요약하기'가 별개 단계임을
#   코드 구조로 보여주는 교육용 의도다(알려진 트레이드오프, 현재는 2단계 유지).
def llm_distill(dimension: Dimension, reason_prompt: str) -> WorkerArtifact:
    """Reason over the rendered source in the worker's own context, then compress (A2)."""
    # 1차 호출 = 추론(reason): 원시 데이터가 담긴 질문지를 LLM에 주고 자유 서술형 분석문을 받는다.
    # temperature=0: AI "창의성 다이얼"을 0으로 — 같은 질문이면 최대한 같은 답(테스트가 쉬워짐).
    reply = ChatAnthropic(model=_MODEL, temperature=0).invoke(reason_prompt)
    # 답변이 텍스트+이미지 등 여러 블록 묶음일 수도 있어, 만일에 대비해 글자(str)로 변환해 둔다.
    analysis = reply.content if isinstance(reply.content, str) else str(reply.content)
    instruction = (
        "Compress this analysis into a bounded artifact: a one-line headline, 3 to 5 key "
        "points, and at least 2 evidence items (each a metric name plus a numeric or string "
        f"value drawn from the data). Analysis:\n{analysis}"
    )
    # 2차 호출 = 압축(compress): 방금 받은 서술문을 "제목1줄+핵심3~5+근거2개 이상"으로 줄이게 한다.
    # with_structured_output: "자유 서술 금지, 반드시 _Distilled 양식에 맞춰 제출"을 강제하는 장치.
    llm = ChatAnthropic(model=_MODEL, temperature=0).with_structured_output(_Distilled)
    out = cast(_Distilled, llm.invoke(instruction))
    # A2의 마지막 방어선: AI가 한도를 넘겨도 오류로 터지지 않고 코드가 직접 잘라서 통과시킨다.
    # 스키마 검사(한도 넘으면 거부하는 문지기)와 이 슬라이싱(애초에 한도 내로 생산하는 공정관리)의
    # 이중 보장 구조다.
    return WorkerArtifact(
        dimension=dimension,
        status="ok",
        headline=out.headline[:200],
        key_points=[p[:200] for p in out.key_points[:5]],
        evidence=out.evidence[:10],
    )


# seed_context: 에피소드 메모리(지난 회의록 한 줄) 주입 — W1 수정의 산물.
# 무슨 기능: 지난 실행 결론 한 줄이 있으면 "지난번엔 이랬다, 달라진 점을 짚어라"라는 메모로
#   바꿔 돌려준다. 지난 기록이 없으면 빈 문자열.
# 역사(W1): 원래는 episodic_seed를 워커까지 전달만 하고 버렸다(편지를 문 앞까지 가져왔는데
#   아무도 안 읽음). 리뷰 W1이 이를 잡아 호출 사슬 전체에 seed를 꿰었고, 이 함수가 최종 수신처다.
# 왜 한 줄만: 지난 보고서 전체를 넣으면 워커 작업대가 부풀고 "요약만 오간다"는 증류 원칙이
#   메모리 경로로 우회된다. 제목 한 줄이면 "연속성"이라는 학습 목표에 충분하다.
# 결정론 워커(orderbook/onchain)는 이 함수를 호출하지 않는다 — 계산기 일에 "지난번 결론"이
#   끼어들 자리가 없기 때문(시그니처상 seed를 받기만 하고 무시).
def seed_context(episodic_seed: dict[str, str] | None) -> str:
    """One-line prior-run note for LLM workers to reference (W1); '' when there is no prior run."""
    if not episodic_seed:
        return ""
    prior_run = episodic_seed.get("prior_run_id", "")
    prior_headline = episodic_seed.get("prior_headline", "")
    return (
        f" For continuity, the prior run ({prior_run}) concluded: {prior_headline}. "
        "Note any change since then."
    )


# WorkerState: 워커가 일하는 동안 들고 다니는 "작업 전표" 양식. LangGraph 각 단계(노드)가
#   이 전표를 주고받는다. CLAUDE.md 규약(typed schema — untyped dict 금지)대로 TypedDict.
# total=False: 모든 칸이 선택 사항 — 작업이 진행되며 칸이 하나씩 채워지기 때문(시작 시엔
#   symbol/mcp_url만, data 단계 후 data 또는 error, 마지막에 artifact).
# data: Any("내용물 불문 택배상자"): 워커마다 다루는 자료 종류가 달라(가격기록/호가창/뉴스/
#   온체인지표) 공용 틀은 내용을 모른 채 운반만 한다. 한 군데서만 쓰는 코드에 제네릭은 과하다.
class WorkerState(TypedDict, total=False):
    symbol: str
    mcp_url: str
    data: Any
    artifact: WorkerArtifact
    error: str
    episodic_seed: dict[str, str] | None


# build_worker_graph: 워커의 작업 순서도(그래프)를 조립하는 공장.
# 하니스의 핵심 계약: 워커는 fetch(어디서,무엇을)->원시데이터 와 work(무엇을,데이터로,지난기록)
#   ->요약 두 함수만 제공하면 된다. 순서도 조립·오류 분기·실패 보고서는 전부 이 공장이 처리.
# checkpointer: 작업 중간 상태를 저장하는 "자동 저장 장치 = 워커 자신의 working-memory 저장소(A4)".
#   A4: 각 워커는 자기 checkpointer DB를 소유, 오케스트레이터가 episodic+long-term DB를 단독 소유
#   (single-writer-per-file). 한 공책에 여러 사람이 동시에 쓰면 엉키므로 "공책당 필기자 한 명".
def build_worker_graph(
    dimension: Dimension,
    fetch: Callable[[str, str], Any],
    work: Callable[[str, Any, dict[str, str] | None], WorkerArtifact],
    checkpointer: Any = None,
) -> Any:
    """``data`` calls ``fetch(mcp_url, symbol)`` (raises on MCP down); ``work`` distills it.

    ``checkpointer`` is the worker's own working-memory store (A4): when set, the graph's
    scratchpad state is persisted to the worker's own DB file.
    """

    # _data 단계: 자료실(MCP)에서 데이터를 가져오되, 먹통이면 비명을 지르며 쓰러지는 대신
    #   전표의 error 칸에 사유를 적는다(A3 실패 모델: 예외를 호출자에게 절대 던지지 않는다).
    #   "출장지가 폐쇄됐습니다"라고 보고서를 쓰는 것이지, 출장 가서 실종되는 게 아니다.
    #   오류 메시지엔 종류 이름(type(exc).__name__)만 — 스택트레이스/경로는 통신선에 안 흘린다.
    def _data(state: WorkerState) -> dict[str, Any]:
        try:
            return {"data": fetch(state["mcp_url"], state["symbol"])}
        except Exception as exc:  # MCP unreachable -> failed, never raise into caller (A3)
            return {"error": f"mcp fetch failed: {type(exc).__name__}"}

    # _work 단계: 분석은 워커별 전문 함수에 맡긴다. 지난 기록(episodic_seed)도 함께 넘긴다.
    def _work(state: WorkerState) -> dict[str, Any]:
        return {"artifact": work(state["symbol"], state["data"], state.get("episodic_seed"))}

    # _fail 단계: 실패조차 정상 양식의 보고서로 만든다(status="failed"). 본부는 성공/실패를
    #   같은 양식으로 받아 "이번에 빠진 분야" 목록으로 집계한다.
    #   A3의 두 번째 약속: 이 경로로 빠지면 AI 호출이 아예 일어나지 않는다(재료가 안 왔으면
    #   유료 요리사를 부르지 않는다).
    def _fail(state: WorkerState) -> dict[str, Any]:
        artifact = WorkerArtifact(
            dimension=dimension,
            status="failed",
            headline=f"{dimension} data unavailable",
            key_points=[state["error"][:200]],
        )
        return {"artifact": artifact}

    # _route: 교통경찰 — error가 있으면 fail, 없으면 work로 보낸다.
    def _route(state: WorkerState) -> str:
        return "fail" if state.get("error") else "work"

    # 작업 순서도 조립(LangGraph 표준 패턴: 노드 등록 → 엣지 연결 → 컴파일). 모양은 다이아몬드:
    #   START → data ─(정상)→ work → END / data ─(error)→ fail → END
    # 3단계짜리에 LangGraph가 거창해 보이나, checkpointer 통합(작업 기억 자동 저장)이 공짜로
    #   따라오고 "워커도 작은 LangGraph 에이전트"라는 시스템 모양을 충족한다.
    graph = StateGraph(WorkerState)
    graph.add_node("data", _data)
    graph.add_node("work", _work)
    graph.add_node("fail", _fail)
    graph.add_edge(START, "data")
    # data가 끝나면 _route에게 묻고 그가 말한 이름의 다음 단계로 간다(판단과 갈림길 목록을 분리).
    graph.add_conditional_edges("data", _route, {"work": "work", "fail": "fail"})
    graph.add_edge("work", END)
    graph.add_edge("fail", END)
    return graph.compile(checkpointer=checkpointer)


# run_worker: 그래프 실행 진입점 — 순서도를 조립하고, 첫 전표를 끼우고, 한 바퀴 돌린 뒤
#   완성된 보고서를 꺼낸다.
def run_worker(
    dimension: Dimension,
    fetch: Callable[[str, str], Any],
    work: Callable[[str, Any, dict[str, str] | None], WorkerArtifact],
    symbol: str,
    mcp_url: str,
    checkpointer: Any = None,
    run_id: str = "run",
    episodic_seed: dict[str, str] | None = None,
) -> WorkerArtifact:
    graph = build_worker_graph(dimension, fetch, work, checkpointer)
    # thread_id=run_id: 자동 저장 장치는 thread_id(서랍 번호) 단위로 상태를 보관한다. 실행 ID를
    #   서랍 번호로 쓰면 실행 한 번마다 새 연습장이 생긴다(working memory = per-run scratchpad).
    # config를 checkpointer가 있을 때만 만드는 이유: 저장 장치 없이 조립한 순서도에 서랍 번호를
    #   주면 LangGraph가 불평한다. 테스트(가짜 부품) 경로는 저장 장치 없이 가볍게 돈다.
    config = {"configurable": {"thread_id": run_id}} if checkpointer is not None else None
    initial = {"symbol": symbol, "mcp_url": mcp_url, "episodic_seed": episodic_seed}
    final = graph.invoke(initial, config=config)
    return cast(WorkerArtifact, final["artifact"])


# _error: 오류 답장을 JSON-RPC 규격 봉투에 담아 보낸다.
# JSON-RPC 독특한 규약: 오류조차 HTTP 200("배달 성공")으로 보내고, 오류 내용은 본문의 error
#   칸에 적는다. HTTP는 우편 배달부일 뿐이고 성공/실패 판정은 봉투(JSON-RPC)가 한다.
def _error(rpc_id: str, code: int, message: str) -> Response:
    body = JsonRpcResponse(id=rpc_id, error=JsonRpcError(code=code, message=message))
    return JSONResponse(body.model_dump())  # JSON-RPC errors travel in a 200 envelope


# build_worker_app: 워커 한 명의 접수 창구 전체를 만든다. 창구는 딱 2개 — POST /(분석 의뢰 접수),
#   GET /.well-known/agent.json(Agent Card = 워커의 명함). A2A에서 외부에 보이는 얼굴의 전부다.
# 왜 FastAPI가 아니라 Starlette: 창구 2개에 자동 문서 생성·의존성 주입은 불필요한 무게다.
#   (FastAPI는 Starlette 위에 얹힌 것이라 얇은 쪽을 직접 썼다.)
def build_worker_app(
    card: AgentCard,
    analyze: Callable[[str, str, dict[str, str] | None], WorkerArtifact],
    mcp_url: str,
) -> Starlette:
    """A2A JSON-RPC service for one worker: ``POST /`` runs ``analyze``, GET serves the card."""

    async def agent_card(request: Request) -> Response:
        return JSONResponse(card.model_dump())

    async def analyze_route(request: Request) -> Response:
        # 접수된 의뢰서를 2단계로 검사한다.
        # (1) 아예 글자가 안 읽히는 편지(JSON 파싱 실패) → -32700(표준 "Parse error").
        try:
            raw: Any = await request.json()
        except Exception:
            return _error("", -32700, "parse error: body is not valid JSON")
        # (2) 읽히긴 하나 서식이 틀린 편지 → -32600(표준 "Invalid Request").
        # 답장엔 "오류 몇 건"(error_count())만 담고 상세는 안 담는다 — 상세문에는 보낸 사람의
        #   입력값이 그대로 메아리칠 수 있어 정보 노출 면적을 줄인다.
        # raw.get("id")를 굳이 꺼내는 이유: 답장에 의뢰서 접수번호(id)를 적어줘야 의뢰인이 어느
        #   의뢰의 답인지 짝을 맞춘다. 서식이 깨져도 접수번호만은 건질 수 있으면 건진다.
        try:
            rpc = JsonRpcRequest.model_validate(raw)
        except ValidationError as exc:
            rpc_id = str(raw.get("id", "")) if isinstance(raw, dict) else ""
            return _error(rpc_id, -32600, f"invalid request: {exc.error_count()} error(s)")
        # 분석을 별도 작업대(스레드)로 보내 돌린다.
        # asyncio.to_thread가 미묘하지만 중요: analyze 내부의 _fetch가 asyncio.run()(새 이벤트루프
        #   까는 명령)을 부른다. 이미 이벤트루프가 도는 창구 안에서 새 루프를 또 깔면 충돌한다.
        #   별도 스레드로 빼면 그곳엔 루프가 없으니 새로 깔아도 합법이 된다(이벤트루프 충돌 회피).
        # rpc.params.episodic_seed를 analyze로 넘기는 이 줄이 W1 수정의 핵심 — 수정 전엔 지난 기록
        #   편지가 바로 여기서 버려졌다.
        artifact = await asyncio.to_thread(
            analyze, rpc.params.symbol, mcp_url, rpc.params.episodic_seed
        )
        # 응답: result=artifact. 통신 양식 자체가 증류 강제 장치 — 요약 보고서가 아닌 것을 실어
        #   보낼 방법이 타입(양식)상 아예 없다.
        return JSONResponse(JsonRpcResponse(id=rpc.id, result=artifact).model_dump())

    # 창구 2개를 달아 접수처를 완성한다. 인증·미들웨어·헬스체크 없음 — 로컬 학습용 최소 구성.
    return Starlette(
        routes=[
            Route("/", analyze_route, methods=["POST"]),
            Route("/.well-known/agent.json", agent_card, methods=["GET"]),
        ]
    )
