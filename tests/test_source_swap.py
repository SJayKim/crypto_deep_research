"""M5 source swap (AC#2/#3/#4): CoinGeckoSource serves get_ohlcv live and delegates the
other 3 tools to fixtures; the COIN_DATA_SOURCE env flips the source; a persistent 429
surfaces as a dimension gap, not a crash. Deterministic -- CoinGecko HTTP is a MockTransport,
no network and no LLM (CLAUDE.md: no live API in tests).

[한글 설명] ARCHITECTURE-MAP §7의 "Fixture↔CoinGecko 스왑"에 해당. 핵심 설계 가치는
"라이브 데이터로 바꿔도 에이전트 코드는 그대로"다(M5). DataSource 인터페이스 뒤에서만
소스가 바뀌므로, COIN_DATA_SOURCE 환경변수 하나로 fixture↔coingecko가 갈린다. 또
rate limit(429)이 터져도 시스템이 죽지 않고 해당 차원만 gap으로 표시(A3 실패 모델)되는지
확인한다. CLAUDE.md 규칙대로 실제 네트워크 호출은 금지 — httpx MockTransport로 응답을 가짜로 만든다.
"""

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from crypto_deep_research.contracts.artifact import WorkerArtifact
from crypto_deep_research.contracts.mcp_tools import OHLCV
from crypto_deep_research.mcp_server.sources.coingecko import CoinGeckoSource, source_from_env
from crypto_deep_research.mcp_server.sources.fixture import FixtureSource
from crypto_deep_research.workers.base import build_worker_graph

_OHLC_PAYLOAD = [
    [1704067200000, 42000.0, 42500.0, 41800.0, 42300.0],
    [1704153600000, 42300.0, 43000.0, 42100.0, 42800.0],
]


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# CoinGecko의 /ohlc 응답(JSON 배열)을 우리 OHLCV 계약 타입으로 정확히 파싱하는지.
# 라이브 소스가 동일한 MCP 스키마를 내놓아 워커가 소스 차이를 모른다는 보장.
def test_get_ohlcv_parses_coingecko_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/coins/bitcoin/ohlc" in str(request.url)
        return httpx.Response(200, json=_OHLC_PAYLOAD)

    result = CoinGeckoSource(client=_client(handler)).get_ohlcv("BTC")
    assert isinstance(result, OHLCV)
    assert result.symbol == "BTC"
    assert len(result.bars) == 2
    assert result.bars[0].close == 42300.0
    assert all(bar.volume == 0.0 for bar in result.bars)  # /ohlc carries no volume


# M5는 ohlcv 한 개만 라이브로 스왑. 나머지 3개 툴은 여전히 fixture로 위임되는지 확인
# (HTTP 클라이언트가 절대 안 불려야 함 → 부분 스왑이 코드 변경 없이 점진적으로 가능).
def test_other_tools_delegate_to_fixture() -> None:
    # The HTTP client must never be touched for the 3 delegated tools.
    src = CoinGeckoSource(client=_client(lambda r: httpx.Response(500)))
    assert src.get_orderbook("BTC") == FixtureSource().get_orderbook("BTC")
    assert src.get_news("BTC") == FixtureSource().get_news("BTC")
    assert src.get_onchain("BTC") == FixtureSource().get_onchain("BTC")


# rate limit이 계속될 때 무한 재시도/먹통이 아니라 깨끗한 HTTPStatusError로 올라오는지.
# 소스 계층이 실패를 삼키지 않고 위로 전파해야 워커가 gap으로 처리할 수 있다(A3).
def test_persistent_429_raises_clean_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "0"})

    src = CoinGeckoSource(client=_client(handler))
    with pytest.raises(httpx.HTTPStatusError):
        src.get_ohlcv("BTC")


# fetch에서 429가 나면 work는 실행조차 안 되고 artifact가 failed로 끝나는지(MCP 죽음과 동일 경로).
# rate limit이 크래시가 아니라 한 차원의 gap으로 격리된다는 A3/소스스왑 안전성의 끝단.
def test_429_surfaces_as_dimension_gap() -> None:
    req = httpx.Request("GET", "http://coingecko/ohlc")
    resp = httpx.Response(429, request=req)

    def fetch(mcp_url: str, symbol: str) -> Any:
        raise httpx.HTTPStatusError("rate limited", request=req, response=resp)

    def work(symbol: str, data: Any, episodic_seed: dict[str, str] | None = None) -> WorkerArtifact:
        raise AssertionError("work must not run when fetch fails")

    final = build_worker_graph("market", fetch, work).invoke(
        {"symbol": "BTC", "mcp_url": "http://mcp"}
    )
    artifact = final["artifact"]
    assert artifact.status == "failed"
    assert artifact.dimension == "market"


# 환경변수 COIN_DATA_SOURCE 하나로 기본 fixture ↔ coingecko가 바뀌는지.
# "라이브 스왑은 설정 한 줄"이라는 M5 핵심 약속을 검증.
def test_source_from_env_swaps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COIN_DATA_SOURCE", raising=False)
    assert isinstance(source_from_env(), FixtureSource)
    monkeypatch.setenv("COIN_DATA_SOURCE", "coingecko")
    assert isinstance(source_from_env(), CoinGeckoSource)
