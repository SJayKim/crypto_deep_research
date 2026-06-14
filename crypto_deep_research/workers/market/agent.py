"""Market worker: a LangGraph ``data -> work`` agent over the MCP boundary.

``data`` pulls OHLCV from the MCP server; ``work`` reasons over the close series in the
worker's own LLM context and distills a bounded ``WorkerArtifact`` (A2). An unreachable
MCP server short-circuits to ``status="failed"`` without touching the LLM (A3). Built on
the shared ``workers/base`` harness (C6).

[한글 설명]
market 워커 = "시세 분석가". LLM 워커의 대표.
- data: MCP 자료실에서 OHLCV(시가·고가·저가·종가·거래량) 가격 기록을 가져온다.
- work: 종가 시계열을 워커 자신의 LLM 컨텍스트(책상)에서 추론한 뒤 한 장 요약으로 증류(A2).
- 입력이 숫자뿐이라 prompt injection 위험이 사실상 없다(외부 글을 다루는 sentiment와 대비).
"""

import asyncio
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from crypto_deep_research.contracts.artifact import WorkerArtifact
from crypto_deep_research.contracts.mcp_tools import OHLCV
from crypto_deep_research.workers.base import llm_distill, run_worker, seed_context


# _fetch_ohlcv: MCP 클라이언트의 정석 시퀀스 — 자료실에 전화 걸어(연결) → 세션 열고 →
#   initialize() 악수(MCP 필수 인사) → get_ohlcv 도구 호출 → 결과를 즉시 양식 검사.
# stdio(같은 컴퓨터 직통 배관)가 아닌 streamable HTTP(네트워크 전화선)인 이유: 자료실 서버가
#   별도 프로세스/컨테이너라서 전화선이 필요하다(DESIGN).
# result.structuredContent를 OHLCV.model_validate로 즉시 검사 — 경계 너머 데이터는 믿지 않고
#   검사대부터 거친다. 연결 재사용 풀 없음(실행당 통화 1회뿐이라 전용 회선은 불필요한 복잡도).
async def _fetch_ohlcv(mcp_url: str, symbol: str) -> OHLCV:
    async with streamable_http_client(mcp_url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("get_ohlcv", {"symbol": symbol})
            return OHLCV.model_validate(result.structuredContent)


# _fetch: 비동기(회전 근무) 자료 요청을, 순서도의 data 단계가 기대하는 동기(한-번에-하나씩)
#   함수로 포장하는 어댑터. 이 asyncio.run이 base.py의 asyncio.to_thread와 짝을 이룬다 —
#   to_thread가 빈 작업대를 내주므로 여기서 새 이벤트루프를 깔아도 충돌이 없다.
def _fetch(mcp_url: str, symbol: str) -> OHLCV:
    return asyncio.run(_fetch_ohlcv(mcp_url, symbol))


# _work: 원시 데이터가 워커의 책상 위에서 소화되는 바로 그 지점.
#   가격 기록에서 날짜:종가 쌍만 뽑아 질문지(프롬프트)를 만들고 공용 증류 함수에 넘긴다.
#   캔들 데이터 중 종가만 쓰고 나머지(시/고/저/거래량)는 버린다 — v1 분석(추세·모멘텀)엔 종가면
#   충분하고 질문지를 불필요하게 키우지 않는다. 1000행이 통째로 들어와도 괜찮다(워커 자신의 책상).
#   숫자만 끼워 넣으므로 prompt injection 위험이 사실상 없다(숫자에는 몰래 지시를 못 심는다).
def _work(symbol: str, ohlcv: OHLCV, episodic_seed: dict[str, str] | None = None) -> WorkerArtifact:
    series = ", ".join(f"{b.ts}:{b.close}" for b in ohlcv.bars)
    prompt = (
        f"You are a crypto market analyst. Analyze {symbol} from these daily close prices "
        f"(unix_ts:close): {series}. Discuss trend, momentum, and notable levels. Be concise "
        "and specific with numbers."
        # seed_context: 지난 실행의 결론 한 줄을 붙인다(W1). 지난 기록이 없으면 빈 문자열이라
        #   질문지는 그대로다.
        f"{seed_context(episodic_seed)}"
    )
    # 워커별 코드의 역할은 질문지 작성까지 — 추론→압축→보고서 증류는 공용 틀이 맡는다.
    return llm_distill("market", prompt)


# analyze_market: 이 워커의 정문(공개 진입점). 내 _fetch/_work 두 부품을 공용 틀에 꽂는
#   한 줄짜리 조립. 이 함수 모양 (symbol, mcp_url, episodic_seed, checkpointer)이 4개 워커
#   공통이며, 접수처(build_worker_app)가 기대하는 analyze 규격과 맞물린다.
def analyze_market(
    symbol: str,
    mcp_url: str,
    episodic_seed: dict[str, str] | None = None,
    checkpointer: Any = None,
) -> WorkerArtifact:
    return run_worker(
        "market",
        _fetch,
        _work,
        symbol,
        mcp_url,
        checkpointer=checkpointer,
        episodic_seed=episodic_seed,
    )
