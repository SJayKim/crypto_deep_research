"""Planner: discover the available workers, then pick the worker set from long-term memory.

``discover`` reads each worker's Agent Card (``GET /.well-known/agent.json``) and maps its
declared skill to a ``Dimension`` -- a data-driven registry, so adding a worker is one env
URL, never an orchestrator edit (AC#7). ``plan_dimensions`` is the long-term READ trigger
(TENSION-B): ``market`` is always analyzed; every other dimension is included only when the
symbol is on the long-term watchlist or a stored fact names it.

[한글 설명]
이 파일은 "팀장이 누구에게 일을 시킬지 정하는" 계획(plan) 단계다. 두 결정이 만난다:
- AC#7 (data-driven registry): 팀원 명단을 코드에 하드코딩하지 않는다. 주소 목록만 주면 각 주소에서
  명함(Agent Card)을 받아와 "이 주소는 시세 담당이구나"를 실행 시점에 알아낸다 → 워커 추가 = 설정에
  주소 한 줄, 오케스트레이터 코드 수정 0줄.
- TENSION-B (장기 메모리 READ 트리거): 메모리가 장식이 되지 않으려면 실제로 행동을 바꿔야 한다.
  여기 plan_dimensions가 장기 메모리(팀장 수첩 — 관심 코인 목록과 배운 사실들)를 읽어, 이번에 어느
  팀원을 투입할지를 실제로 바꾼다.
통신(discover)과 순수 계산(plan_dimensions)을 분리해, 계획 로직은 네트워크 없이 테스트된다.
"""

import asyncio
import re

import httpx

from crypto_deep_research.contracts.a2a import AgentCard
from crypto_deep_research.contracts.artifact import Dimension
from crypto_deep_research.contracts.memory import LongTermMemory

# 4개 분석 차원의 "공식 순서". 순서 있는 튜플인 이유: 맨 마지막에 결과를 이 순서대로 정렬해 돌려주기 위함.
# 앞의 _ 는 "이 파일 안에서만 쓰는 내부용" 표시 — 이 순서는 플래너의 내부 사정이다.
_DIMENSIONS: tuple[Dimension, ...] = ("market", "orderbook", "sentiment", "onchain")


# [기능] 명함의 특기란(skills, 예: ["analyze:market"])을 보고 무슨 담당인지 알아낸다.
# [왜] "analyze:<차원>" 표기가 워커→팀장의 자기소개 프로토콜. 아는 특기가 하나도 없으면 None("모르겠음")을
#      돌려줘 그 워커는 무시한다 — 정체 모를 워커가 섞여도 시스템은 계속 굴러간다(에러 안 냄).
def _skill_dimension(card: AgentCard) -> Dimension | None:
    for dimension in _DIMENSIONS:
        if f"analyze:{dimension}" in card.skills:
            return dimension
    return None


# [기능] 워커의 명함을 인터넷에서 받아온다(Agent Card 디스커버리).
# [왜] A2A 약속상 명함은 항상 /.well-known/agent.json 라는 정해진 주소에 있다. 제한시간 10초가 dispatch의
#      30초와 별개 고정값인 건, 명함 조회는 작은 파일을 건네주는 빠른 일이고 설정화 요구도 없었기 때문.
async def _fetch_card(worker_url: str) -> AgentCard:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(f"{worker_url}/.well-known/agent.json")
    return AgentCard.model_validate(response.json())


# [기능] 모든 주소에서 명함을 동시에 받아와 "담당→주소" 명단(registry)을 만든다.
# [왜] AC#7의 실현 — 명단이 데이터(설정)에서 만들어진다. 명함 받기도 fan_out과 같은 asyncio.gather 패턴.
async def discover(worker_urls: list[str]) -> dict[Dimension, str]:
    """Map each worker URL to its dimension via its Agent Card (data-driven registry)."""
    # 명함 받기 실패(워커가 꺼져 있음)는 여기서 잡지 않는다 — gather가 비상벨을 그대로 올린다.
    # (dispatch와 달리 발견 단계의 부분 실패 흡수는 현 단계 범위 밖.)
    cards = await asyncio.gather(*[_fetch_card(url) for url in worker_urls])
    registry: dict[Dimension, str] = {}
    # zip(..., strict=True): 주소 수와 명함 수가 어긋나면 조용히 잘라버리지 않고 즉시 에러(zip의 고전적 함정 차단).
    for url, card in zip(worker_urls, cards, strict=True):
        dimension = _skill_dimension(card)
        if dimension is not None:
            registry[dimension] = url
    # 이후 모든 단계는 "주소"가 아니라 "담당"으로 생각한다. 주소는 실제 전화 직전에만 다시 등장.
    return registry


# [기능] TENSION-B의 핵심 — 장기 메모리를 읽어 이번에 투입할 담당 집합을 정한다.
# [왜] async가 없는(순수) 함수다. 통신(명함 받기)과 계획(머릿속 계산)을 분리해, 가짜 수첩만 끼우면 테스트된다.
def plan_dimensions(
    symbol: str, registry: dict[Dimension, str], longterm: LongTermMemory
) -> list[Dimension]:
    """Long-term READ: market always; others iff watchlisted or named by a stored fact."""
    chosen: set[Dimension] = set()
    # 계획 규칙 1: 시세(market)는 무조건 분석한다(그 담당이 명단에 있는 한). 수첩이 텅 빈 첫 실행에도 보고서가 빈손이 아니게.
    if "market" in registry:
        chosen.add("market")
    # 여기가 장기 메모리 READ 트리거의 실제 지점. watchlist()(관심 코인 목록)와 facts(symbol)(배운 사실들)을 읽는다.
    watched = symbol in longterm.watchlist()
    # fact_tokens: 리뷰 O2의 수정 결과. 사실 문장을 소문자 → 단어(영숫자 토큰) 집합으로 쪼갠다.
    # 원래는 부분 문자열 매칭이라 "blockchain" 속 "chain"에 onchain이 켜지는 등 거의 모든 차원이 항상 선택돼
    # TENSION-B 시연이 무너졌다. 이제 정확히 'onchain'이라는 단어가 있어야 onchain 담당이 선택된다.
    fact_tokens = set(re.findall(r"[a-z0-9]+", " ".join(longterm.facts(symbol)).lower()))
    # 계획 규칙 2: 시세 외 담당은 (a) 관심 코인이거나 (b) 저장된 사실이 그 담당 이름을 단어로 언급할 때만 투입.
    for dimension in registry:
        if dimension == "market":
            continue
        if watched or dimension in fact_tokens:
            chosen.add(dimension)
    # chosen은 집합이라 순서가 매번 다를 수 있으므로, 공식 순서표 _DIMENSIONS로 걸러 항상 같은 순서의 목록으로 만든다
    # (출력 순서가 일정해야 테스트·로그가 흔들리지 않음).
    return [d for d in _DIMENSIONS if d in chosen]
