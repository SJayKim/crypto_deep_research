"""M3 AC#6: the planner's long-term READ -- watchlist/facts shape the worker set (T7b).

[한글 설명] ARCHITECTURE-MAP §7의 "long-term READ가 plan 변경"에 해당. 5대 개념 중 Layered
Memory의 long-term READ 트리거 — premise 5("모든 메모리 계층은 실제 트리거가 있어야 장식이
아니다")의 핵심. TENSION-B에 따라 READ 트리거(플래너가 워커 집합 선택)는 M3 fan-out과 함께
출시한다. 여기서는 watchlist/facts 내용이 실제로 plan_dimensions의 결과(어떤 워커를 돌릴지)를
바꾸는지, 그리고 부분 문자열이 우연히 차원을 선택하지 않는지(정확 토큰 매칭)를 검증한다. 스텁 메모리(T7b).
"""

from collections.abc import Callable

from crypto_deep_research.contracts.artifact import Dimension
from crypto_deep_research.contracts.memory import LongTermMemory
from crypto_deep_research.orchestrator.planner import plan_dimensions

_REGISTRY: dict[Dimension, str] = {
    "market": "http://w/market",
    "orderbook": "http://w/orderbook",
    "sentiment": "http://w/sentiment",
    "onchain": "http://w/onchain",
}


# 기억이 비면 기본값으로 market만 돌린다(가장 보수적인 plan). 기준선 검증.
def test_empty_memory_plans_market_only(longterm: Callable[..., LongTermMemory]) -> None:
    assert plan_dimensions("BTC", _REGISTRY, longterm()) == ["market"]


# watchlist에 든 심볼은 4개 워커 전부 돌린다. long-term READ가 plan을 확장한다는 핵심(AC#6).
def test_watchlisted_symbol_plans_full_set(longterm: Callable[..., LongTermMemory]) -> None:
    chosen = plan_dimensions("BTC", _REGISTRY, longterm(watchlist=["BTC"]))
    assert chosen == ["market", "orderbook", "sentiment", "onchain"]


# 학습된 fact가 특정 차원(onchain)을 언급하면 그 차원만 추가로 promote되는지. 선택적 확장 검증.
def test_fact_adds_only_the_named_dimension(longterm: Callable[..., LongTermMemory]) -> None:
    memory = longterm(facts={"BTC": ["onchain: large exchange outflow observed"]})
    assert plan_dimensions("BTC", _REGISTRY, memory) == ["market", "onchain"]


# "sentimental"에 "sentiment"가 부분 포함돼도 차원으로 오인 선택하지 않는지(정확 토큰 매칭).
# 우연한 단어가 워커를 잘못 켜는 오탐을 막는다.
def test_incidental_substring_does_not_select(longterm: Callable[..., LongTermMemory]) -> None:
    # "sentimental" contains "sentiment" as a substring; exact-token match must NOT promote it.
    memory = longterm(facts={"BTC": ["sentimental retail buyers stepped back"]})
    assert plan_dimensions("BTC", _REGISTRY, memory) == ["market"]
