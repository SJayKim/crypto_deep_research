"""FixtureSource: serves the 4 tools from local JSON fixtures (day-one DataSource).

[한글 설명]
이 파일은 "첫날(day one)" 데이터 출처다 — 인터넷 없이, 미리 만들어 둔 견본(fixture) JSON
파일로 도구 4개를 그대로 채운다. DataSource 자격 요건만 맞추면 되므로 이걸 갖고 시스템 전체를
실제 API 없이 돌리고 테스트할 수 있다. 나중에 M5에서 CoinGeckoSource가 들어와도 이 견본
출처는 나머지 도구를 받쳐주는 부품으로 계속 쓰인다.
"""

import json
from pathlib import Path
from typing import Any

from crypto_deep_research.contracts.mcp_tools import OHLCV, News, OnchainMetrics, Orderbook

# 견본 JSON 폴더를 "이 소스 파일 위치 기준"으로 찾는다(__file__ 기준).
# [왜] 어느 폴더에서 실행하든(cwd) — 내 컴퓨터든 컨테이너 안이든 — 항상 같은 fixtures 폴더를
#   찾기 위해서. "실행한 자리 기준으로 길을 적었다가 다른 데서 길을 잃는" 고전적 함정을 피한다.
_FIXTURES = Path(__file__).parent / "fixtures"


# [기능] 로컬 JSON 견본으로 4개 도구를 제공하는 출처.
# [주목] DataSource를 상속하지 않는다 — Protocol(자격 요건)이라 메서드 4개의 모양만 맞으면 된다.
class FixtureSource:
    # 견본 폴더 위치(root)를 바깥에서 바꿔 끼울 수 있게 둔다(테스트가 임시 폴더의 가짜 견본을
    # 쓰기 위한 최소한의 구멍). 기본값은 패키지에 같이 들어있는 fixtures.
    def __init__(self, root: Path = _FIXTURES) -> None:
        self._root = root

    # [기능] 심볼+도구 이름으로 파일명을 조립해 그 JSON을 읽는다. 규약: `{심볼}_{도구}.json`
    #   (예: btc_ohlcv.json, btc_news.json). 규칙 하나 덕에 도구 4개의 파일 읽기가 하나로 합쳐진다.
    # [의도된 실패] 없는 심볼이면 FileNotFoundError가 그냥 터진다 — 일부러 안 잡는다. 이 에러는
    #   워커의 data 노드에서 "이 항목은 데이터를 못 구함"(dimension gap)으로 변환된다(A3: 실패는
    #   보고서의 데이터가 되지 침묵하지 않는다). 견본 파일은 btc_*.json만 존재(리뷰 02 S3의 한계).
    def _load(self, symbol: str, tool: str) -> Any:
        path = self._root / f"{symbol.lower()}_{tool}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    # JSON 내용을 "검사하면서" 공식 서식(Pydantic 모델)에 옮겨 담는다 — model_validate가 검사원
    # 역할이라 견본이 서식과 어긋나면 여기서 즉시 터진다(견본조차 계약 검사를 통과해야 나간다).
    # interval(캔들 간격)은 받지만 쓰지 않는다: 견본은 간격 구분 없이 한 벌뿐. 자격 요건의 모양을
    # 맞추려 받기만 하는 것이고, 간격별 견본을 다 만드는 건 불필요한 정교화다.
    def get_ohlcv(self, symbol: str, interval: str = "1d") -> OHLCV:
        return OHLCV.model_validate(self._load(symbol, "ohlcv"))

    # 아래 3개도 같은 패턴 — 도구 이름과 서식만 다르다.
    def get_orderbook(self, symbol: str) -> Orderbook:
        return Orderbook.model_validate(self._load(symbol, "orderbook"))

    def get_news(self, symbol: str) -> News:
        return News.model_validate(self._load(symbol, "news"))

    def get_onchain(self, symbol: str) -> OnchainMetrics:
        return OnchainMetrics.model_validate(self._load(symbol, "onchain"))
