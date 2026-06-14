"""MCP tool I/O schemas: get_ohlcv, get_orderbook, get_news, get_onchain.

[한글 설명]
MCP 서버(에이전트가 외부 도구·자료를 쓰게 해주는 표준 창구)가 제공하는 4개 도구의
"반환 데이터 양식". 워커 4명이 각자 자기 도구를 호출한다
(market→OHLCV, orderbook→Orderbook, sentiment→News, onchain→OnchainMetrics).
핵심: 이 양식들에는 분량 제한이 "없다" — artifact.py와 정반대이며 이게 의도적이다.
MCP 경계(자료실→담당자)로는 원시 데이터가 아무리 크게 흘러와도 되고,
A2A 경계(담당자→팀장)에서는 증류된 요약만 나간다. 두 경계의 비대칭이 이 아키텍처의 요점.
"""

from pydantic import BaseModel


# 가격 차트 데이터의 양식. OHLCV = 시가·고가·저가·종가·거래량,
# 즉 가격 차트의 캔들(막대) 하나에 적히는 다섯 숫자.
class OHLCVBar(BaseModel):
    ts: int  # 캔들 시각
    open: float
    high: float
    low: float
    close: float
    volume: float


class OHLCV(BaseModel):
    symbol: str
    interval: str  # 캔들 간격, 예: "1h"
    bars: list[OHLCVBar]  # 개수 상한 없음 — 원시 데이터는 MCP 경계로 무제한 허용(위 설명대로 의도)


# 호가창(사겠다/팔겠다 주문이 줄 서 있는 판) 데이터의 양식. 호가 한 단계 = (가격, 수량).
class OrderbookLevel(BaseModel):
    price: float
    size: float


class Orderbook(BaseModel):
    symbol: str
    bids: list[OrderbookLevel]  # 매수 호가
    asks: list[OrderbookLevel]  # 매도 호가 — 매수/매도 벽·스프레드 분석의 원재료


# 뉴스 데이터의 양식. 핵심 계약: 감성 점수가 "도구 쪽에서 이미 계산돼" 들어온다.
# sentiment 워커는 점수를 종합·해석할 뿐, 기사 본문을 읽고 감성을 추출하지 않는다.
# 본문 칸이 아예 없는 것도 같은 이유 — 본문을 넘기면 워커 컨텍스트가 부풀고,
# prompt injection 표면(외부 텍스트가 AI 지시문에 흘러들 접촉 면적)도 커진다.
class NewsItem(BaseModel):
    title: str
    source: str
    sentiment: float  # -1.0..1.0  # -1.0(매우 부정) .. 1.0(매우 긍정)


class News(BaseModel):
    symbol: str
    items: list[NewsItem]


# 온체인(블록체인 장부에서 직접 읽은) 지표의 양식. 다른 셋과 달리 목록이 아닌
# "현재 시점 스냅샷 한 장"이다 — v1 온체인 분석엔 시계열이 아닌 현재 지표 3개면 충분하다고 봄.
class OnchainMetrics(BaseModel):
    symbol: str
    active_addresses: int  # 활성 주소 수 (네트워크 사용 활성도)
    tx_volume: float  # 트랜잭션 볼륨
    exchange_netflow: float  # 거래소 순유입 (양수=입금 우세→매도 압력 신호로 해석되곤 함)
