"""A2A service for the market worker: the shared harness + the market Agent Card.

[한글 설명] service.py는 워커의 "접수 창구" — 명함(Agent Card) 작성 + 분석 함수 연결뿐.
이 파일이 22줄로 끝나는 건 C6 공용 틀 추출의 직접 효과다(4개 워커 service.py가 판박이).
"""

from functools import partial
from typing import Any

from starlette.applications import Starlette

from crypto_deep_research.contracts.a2a import AgentCard
from crypto_deep_research.workers.base import build_worker_app
from crypto_deep_research.workers.market.agent import analyze_market


# build_market_app: 명함 내용을 적고, 분석 함수를 접수처에 연결한다.
def build_market_app(mcp_url: str, public_url: str, checkpointer: Any = None) -> Starlette:
    card = AgentCard(
        name="market-worker",
        description="Crypto market analysis (OHLCV trend/momentum) as a WorkerArtifact.",
        url=public_url,
        version="0.1.0",
        # skills=["할 수 있는 일:분야"] 형식의 명함 한 줄. 정적 명함(A1)이나 형식은 A2A 관행을 따른다.
        skills=["analyze:market"],
    )
    # partial(analyze_market, checkpointer=...): 자동 저장 장치를 미리 끼운 채 함수를 포장해
    #   접수처가 기대하는 analyze(symbol, mcp_url, seed) 모양으로 만든다. 이 주입 경로가 W2 수정의
    #   산물 — 수정 전엔 저장 장치를 만들어 놓고 아무도 안 끼워 working layer가 죽어 있었다.
    #   serve_worker.py가 자기 DB로 저장 장치를 열어(A4: 공책당 필기자 한 명) 여기로 흘려보낸다.
    return build_worker_app(card, partial(analyze_market, checkpointer=checkpointer), mcp_url)
