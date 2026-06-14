"""CoinGeckoSource: live ``get_ohlcv`` from CoinGecko; the other 3 tools use fixtures.

The M5 live swap (AC#2) is this file + env only. ``get_ohlcv`` hits CoinGecko's
``/coins/{id}/ohlc`` (that endpoint carries no volume -> ``volume=0.0``); the remaining
tools delegate to ``FixtureSource`` so the MCP tool surface is unchanged. A 429 is
retried with backoff then raised; the worker's data node turns that into a dimension gap
(A3), never an unhandled crash (AC#4).

[한글 설명]
이 파일은 M5의 "라이브 출처"다. M5의 목표는 "API를 많이 연동하기"가 아니라 "같은 MCP 도구
뒤에서 출처를 바꿔도 에이전트가 눈치채지 못한다"는 것의 증명이다. 그래서 도구 4개 전부가
아니라 get_ohlcv "하나만" CoinGecko 실데이터로 가고, 나머지 3개는 견본에 그대로 맡긴다(증명엔
하나면 충분 — Simplicity First). rate limit(429, 방문 횟수 초과)에 걸리면 서버가 적어준 대기
시간을 존중하며 재시도하고, 끝까지 막히면 조용히 견본으로 대체하지 않고 깨끗한 에러로 위에
올려 보낸다(A3 / AC#4). API 키는 코드가 아니라 env에서만 읽고, 주소가 아니라 헤더로 보낸다.
"""

import os
import time
from typing import Any

import httpx

from crypto_deep_research.contracts.mcp_tools import (
    OHLCV,
    News,
    OHLCVBar,
    OnchainMetrics,
    Orderbook,
)
from crypto_deep_research.mcp_server.sources.base import DataSource
from crypto_deep_research.mcp_server.sources.fixture import FixtureSource

# CoinGecko와 대화할 때 쓸 주소·번역표·재시도 규칙을 한곳에 모은 상수들.
_BASE = "https://api.coingecko.com/api/v3"
# 심볼 번역표: 우리는 "BTC"로 말하지만 CoinGecko는 자기들 이름표(coin id, "bitcoin")로 말한다.
# 이번 단계 범위(BTC, +ETH)만큼만 채워져 있다. 표에 없는 심볼은 아래에서 symbol.lower()로 추측
# 하는데 틀리면 404가 날 수 있음 → "BTC 한 종목이 이번 목표라 현행 허용, 한계는 글로 남김"(리뷰 02 S3).
_SYMBOL_TO_ID = {"BTC": "bitcoin", "ETH": "ethereum"}
# 우리 캔들 간격 표기(1d 등)를 CoinGecko가 알아듣는 days 값으로 바꾸는 번역표.
_INTERVAL_TO_DAYS = {"1d": "1", "1w": "7", "1m": "30"}
# 재시도 규칙(매직 넘버를 본문에 묻지 않고 이름 붙여 맨 위에 둔다): 총 2회, 기본 대기 0.5초.
_RETRIES = 2
_BACKOFF_BASE_S = 0.5


# [기능] 상대 서버가 "몇 초 뒤 다시 와라"라고 적어준 쪽지(Retry-After 헤더)를 읽되, 없거나
#   숫자가 아니면 우리 기본 대기 시간을 쓴다.
# [왜 방어하나] 헤더는 남의 서버가 보내는 외부 입력이라 무엇이든 적혀 올 수 있다 — 숫자 변환
#   실패는 "일어날 리 없는 시나리오"가 아니라 실제로 일어나는 시나리오라 막는다. rate limit에
#   걸렸을 때 서버가 기다리라는 시간을 존중하는 것이 정석 대응이다.
def _retry_after(resp: httpx.Response, default: float) -> float:
    header = resp.headers.get("Retry-After")
    if header is None:
        return default
    try:
        return float(header)
    except ValueError:
        return default


# [기능] get_ohlcv만 CoinGecko 실데이터로, 나머지 3개는 견본에 위임하는 라이브 출처.
# [주목] FixtureSource를 부품으로 "품는" 방식(합성, composition)이지 자식 클래스(상속)가 아니다.
class CoinGeckoSource:
    # 부품 2개를 바깥에서 갈아끼울 수 있게 한다: fixture(일을 떠넘길 견본 출처)와 client(인터넷
    # 요청을 보내는 전화기 역할의 HTTP 클라이언트). 테스트는 가짜 전화기를 꽂아 실제 인터넷 호출
    # 없이 429 상황과 응답 해석을 검증한다(CLAUDE.md: 테스트에서 CoinGecko 응답은 mock).
    def __init__(
        self, fixture: FixtureSource | None = None, client: httpx.Client | None = None
    ) -> None:
        self._fixture = fixture or FixtureSource()
        # timeout=10.0: 응답이 없으면 10초까지만 기다리고 끊는다 — 외부 API에 무한정 매달리지
        # 않으며, 워커 전체 제한시간(A3, 30초) 안에 안전하게 들어오는 여유.
        self._client = client or httpx.Client(timeout=10.0)
        # API 키(서비스 출입증)는 env에서만 읽는다(NFR#3 "키는 .env", 코드에 직접 적힌 키 없음).
        # 없으면 빈 문자열 — CoinGecko 무료(demo) 등급은 키 없이도 동작하므로 키를 강제하지 않는다.
        self._api_key = os.environ.get("COINGECKO_API_KEY") or ""

    # 흐름: 심볼→CoinGecko 이름표 번역 → 요청 조건 구성 → HTTP GET → CoinGecko가 주는 숫자 나열
    #   [시각,시가,고가,저가,종가]을 우리 공식 서식 OHLCVBar로 옮겨 담기 → 마지막 줄에서 contracts
    #   서식으로 변환(실데이터든 견본이든 밖으로 나가는 모양은 동일 = MCP 경계 유지).
    def get_ohlcv(self, symbol: str, interval: str = "1d") -> OHLCV:
        coin_id = _SYMBOL_TO_ID.get(symbol.upper(), symbol.lower())
        params = {"vs_currency": "usd", "days": _INTERVAL_TO_DAYS.get(interval, "1")}
        # 출입증(API 키)을 헤더로 동봉한다 — URL 뒤에 붙이지 않는 이유: 주소는 로그에 남기 쉬워
        # 키가 새어 나갈 표면을 줄이려는 것(리뷰 02 ③).
        headers = {"x-cg-demo-api-key": self._api_key} if self._api_key else {}
        rows = self._get_json(f"{_BASE}/coins/{coin_id}/ohlc", params, headers)
        # [volume=0.0 고정 — 리뷰 02 S2] 이 엔드포인트(/coins/{id}/ohlc)는 거래량을 안 준다.
        #   지금 market 워커는 시각·종가만 쓰므로 무해하나, 나중에 거래량 기반 판단이 생기면 조용히
        #   "거래량 0"으로 오작동할 수 있는 지점. 결론은 "한계를 글로 남기고 현행 유지"(개선하려면
        #   /market_chart 엔드포인트로 교체). 데이터의 빈칸을 숨기지 않고 기록한 한계로 만든 사례.
        bars = [
            OHLCVBar(ts=int(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=0.0)
            for r in rows
        ]
        return OHLCV(symbol=symbol.upper(), interval=interval, bars=bars)

    # 나머지 3개 도구는 견본 출처에 그대로 떠넘긴다(위임) — 손님에게 보이는 창구 4개는 그대로
    # 두면서(MCP tool surface unchanged) 실데이터 전환은 1개 창구에만 적용.
    def get_orderbook(self, symbol: str) -> Orderbook:
        return self._fixture.get_orderbook(symbol)

    def get_news(self, symbol: str) -> News:
        return self._fixture.get_news(symbol)

    def get_onchain(self, symbol: str) -> OnchainMetrics:
        return self._fixture.get_onchain(symbol)

    # [기능] 429(rate limit)만 특별 취급해 기다렸다 다시 가는 재시도 반복문. 에러 성격별 대응:
    #   - 429가 아닌 에러(404 없음, 500 고장 등): 다시 가도 똑같을 가능성이 커 raise_for_status()로
    #     즉시 에러를 올린다.
    #   - 429: 일시적 혼잡 → 서버 대기 쪽지(없으면 0.5초→1.0초로 점점 길게 = 지수 백오프)만큼
    #     기다렸다 재시도, 총 2회.
    def _get_json(self, url: str, params: dict[str, str], headers: dict[str, str]) -> Any:
        for attempt in range(_RETRIES):
            resp = self._client.get(url, params=params, headers=headers)
            if resp.status_code != 429:
                resp.raise_for_status()
                return resp.json()
            time.sleep(_retry_after(resp, _BACKOFF_BASE_S * 2**attempt))
        # 반복이 끝나면(=2번 다 429) 마지막으로 한 번 더 시도하고, 그래도 429면 에러를 던진다.
        # 핵심: 끝까지 막혀도 조용히 빈/대체 데이터를 돌려주지 않고 깨끗한 에러로 끝낸다. 그 에러는
        # 워커 data 노드가 받아 "이 차원은 비었음"(dimension gap)으로 변환하고(A3) 부분 보고서를
        # 낸다 — 시스템은 죽지도 모른 척하지도 않는다.
        resp = self._client.get(url, params=params, headers=headers)
        resp.raise_for_status()  # a 429 on the final attempt raises -> dimension gap (AC#4)
        return resp.json()


# [기능] 환경변수(설정 쪽지) 한 장으로 출처를 고르는 스위치.
# [왜 기본값이 fixture인가] 쪽지에 명시적으로 "coingecko"라고 적어야만 실데이터로 간다(라이브는
#   켜겠다고 선택해야 켜지는 옵트인). 출입증 없이, 인터넷 없이 띄워도 기본 동작이 안전하다.
#   "coingecko" 외의 모든 값(오타 포함)은 견본으로 떨어진다(리뷰 02 ②). 반환 타입이 구체 클래스가
#   아니라 DataSource(자격 요건)라, 부르는 쪽(__main__.py)은 어느 쪽이 왔는지 영원히 모른다.
#   이 스위치 하나가 곧 M5 AC#2(fixture→live env-only 교체)의 전부다.
def source_from_env() -> DataSource:
    """Pick the MCP server's data source from ``COIN_DATA_SOURCE`` (default ``fixture``)."""
    if os.environ.get("COIN_DATA_SOURCE", "fixture").lower() == "coingecko":
        return CoinGeckoSource()
    return FixtureSource()
