"""DataSource: the read-only coin-data interface the MCP server is built on.

FixtureSource implements it day one; CoinGeckoSource swaps in at M5 with no agent
code change (the MCP boundary holds).

[한글 설명]
이 파일은 "코인 데이터 출처(source)라고 불리려면 무엇을 할 수 있어야 하는가"를
적어둔 자격 요건서(DataSource Protocol)다. MCP 서버는 이 요건서만 보고 일하므로,
요건만 맞으면 견본(FixtureSource)이든 실데이터(CoinGeckoSource)든 자유롭게 갈아끼울
수 있다. 첫날엔 견본이 이 자격을 채우고, M5에 CoinGecko가 들어와도 워커/오케스트레이터
코드는 한 줄도 안 바뀐다 — 이것이 "MCP 경계가 버틴다"는 말의 실체다.
"""

from typing import Protocol

from crypto_deep_research.contracts.mcp_tools import OHLCV, News, OnchainMetrics, Orderbook


# [기능] "코인 데이터 출처"의 자격 요건서. 아래 4개 메서드는 MCP 도구 4개와 1:1로 대응한다.
# [왜 상속(ABC)이 아니라 Protocol인가] 상속은 "특정 부모의 자식이어야 함"을 따지는 혈통
#   검사지만, Protocol은 "모양(메서드 4개)만 맞으면 인정"하는 구조적 타이핑이다. 그래서
#   FixtureSource도 CoinGeckoSource도 이 클래스를 상속하지 않는다 — 채용 비유로는 "특정
#   학교 출신"이 아니라 "이 4가지 업무가 가능한 사람"을 뽑는 것. mypy가 합격 여부를 검사한다.
# [반환 형식] 모두 contracts 모델 — 출처가 무엇이든 통신선에 실려 나가는 데이터의 모양은 같다.
class DataSource(Protocol):
    # 심볼의 최근 OHLCV(시·고·저·종가) 캔들. interval은 캔들 간격(일봉/주봉 등).
    def get_ohlcv(self, symbol: str, interval: str) -> OHLCV: ...

    # 심볼의 호가창 최상단(매수/매도 호가).
    def get_orderbook(self, symbol: str) -> Orderbook: ...

    # 심볼 관련 최근 뉴스 헤드라인(+감성 점수).
    def get_news(self, symbol: str) -> News: ...

    # 심볼의 온체인 활동 지표.
    def get_onchain(self, symbol: str) -> OnchainMetrics: ...
