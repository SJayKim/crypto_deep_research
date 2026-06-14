"""MCP server: 4 read-only coin-data tools over streamable HTTP, backed by a DataSource.

Stateless and read-only (A4): every tool call reads the source and returns; no shared
mutable state, so concurrent calls return identical data. Run with:
``python -m crypto_deep_research.mcp_server.server`` (streamable HTTP on 127.0.0.1:8000/mcp).

[한글 설명]
이 파일은 "에이전트→도구" 경계에 서는 코인 데이터 MCP 서버를 조립하는 곳이다(서버 팩토리).
MCP는 'AI가 외부 도구를 쓸 때 따르는 표준 규격' — 전기 콘센트 규격에 비유된다. 워커 4명이
이 콘센트에 동시에 꽂아 각자 필요한 데이터를 가져간다. 성격 둘: (1) 무상태+읽기 전용(A4) —
아무것도 기억하지 않고 매번 출처(source)를 읽어 돌려줄 뿐이라, 동시에 물어봐도 줄 세우기 없이
안전하고 늘 같은 답이 나온다. (2) 도구 표면(창구 4개)은 고정, 그 뒤 자료실(DataSource)만 교체.
서버 부품 자체는 공식 SDK(FastMCP)를 쓴다 — A2A는 직접 짰지만(의도된 비대칭) MCP는 "경계를
어디에 두는가"가 학습 목표라 이미 정해진 규격을 다시 만들지 않는다("도로는 직접 깔지 않는다").
"""

from mcp.server.fastmcp import FastMCP

# 돌려주는 데이터 형식은 전부 contracts의 Pydantic 모델(공유 계약 C5). MCP 경계를 넘는
# 데이터도 아무 형태나 담는 dict가 아니라 칸이 정해진 공식 서식에 담는다.
from crypto_deep_research.contracts.mcp_tools import OHLCV, News, OnchainMetrics, Orderbook
from crypto_deep_research.mcp_server.sources.base import DataSource
from crypto_deep_research.mcp_server.sources.fixture import FixtureSource


# [기능] 서버를 즉석에서 만들지 않고 주문을 받아 조립해 주는 "조립 공장(팩토리 함수)".
# [왜] 부르는 쪽이 출처(source)와 접속 주소(host)를 골라 넣어 조립하므로, 테스트에서는
#   build_server(가짜_source)로 실제 인터넷 호출 없이 서버를 띄울 수 있다(테스트 라이브 호출 금지).
def build_server(source: DataSource | None = None, host: str | None = None) -> FastMCP:
    # source 기본값=FixtureSource(): 아무것도 안 넣으면 견본 데이터로 동작하는 안전한 기본값.
    # 타입은 DataSource(자격 요건)뿐 — 뒤가 견본인지 CoinGecko인지 모른 채 정해진 4개 기능만
    # 부른다. 그래서 출처를 갈아끼워도 이 파일은 안 고친다.
    src: DataSource = source or FixtureSource()
    # host set (e.g. 0.0.0.0 under compose) binds non-localhost and skips FastMCP's
    # localhost-only DNS-rebinding guard so in-cluster workers can reach it; None = default.
    # [한글] host가 주어지면 그 주소로 문을 열고, 없으면 SDK 기본(localhost + DNS-rebinding
    #   잠금장치)을 그대로 둔다. compose 환경에서는 워커들이 집 밖 주소(mcp:8000)로 찾아오므로
    #   MCP_HOST=0.0.0.0을 줘 그 잠금장치를 푼다(의도된 in-cluster 접근, 무인증은 이번 epic 밖).
    #   "필요할 때만 기본에서 벗어난다" — host=None을 굳이 넘기지 않는 이유.
    mcp = FastMCP("coin-data", host=host) if host else FastMCP("coin-data")

    # [@mcp.tool()] 이 표시(데코레이터) 한 줄이면 SDK가 함수의 입출력 형식과 docstring을 읽어
    #   "이런 도구가 있어요"라는 안내문을 자동 생성해 워커에게 보여준다(직접 짜면 수십 줄).
    # [본문 한 줄] 서버는 얇은 중계자(어댑터)다 — 실제 일은 출처(src)가 하고 서버는 MCP 규격으로
    #   포장만 한다. 호출마다 출처를 읽고 끝, 임시 저장소/호출 횟수표/손님 기록 없음 = A4 무상태.
    # 워커 대응: market→get_ohlcv, orderbook→get_orderbook, sentiment→get_news, onchain→get_onchain.
    @mcp.tool()
    def get_ohlcv(symbol: str, interval: str = "1d") -> OHLCV:
        """Recent OHLCV bars for a symbol."""
        return src.get_ohlcv(symbol, interval)

    @mcp.tool()
    def get_orderbook(symbol: str) -> Orderbook:
        """Top-of-book bids and asks for a symbol."""
        return src.get_orderbook(symbol)

    @mcp.tool()
    def get_news(symbol: str) -> News:
        """Recent news headlines with sentiment for a symbol."""
        return src.get_news(symbol)

    @mcp.tool()
    def get_onchain(symbol: str) -> OnchainMetrics:
        """On-chain activity metrics for a symbol."""
        return src.get_onchain(symbol)

    return mcp


# 이 파일을 직접 실행하면 견본 기본값으로 서버를 켜는 개발용 지름길.
# transport="streamable-http"가 위에서 설명한 "대표 전화(HTTP)" 방식(127.0.0.1:8000/mcp).
# 정식 출입구는 env를 읽는 __main__.py 쪽이다.
if __name__ == "__main__":
    build_server().run(transport="streamable-http")
