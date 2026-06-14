"""Process entry for the MCP server: ``python -m crypto_deep_research.mcp_server``.

Env-driven for packaging (M5): ``COIN_DATA_SOURCE=coingecko`` serves ``get_ohlcv`` live,
anything else keeps all 4 tools on fixtures; ``MCP_HOST`` (e.g. ``0.0.0.0`` under compose)
sets the bind address. The fixture->live swap stays env-only (AC#2).

[한글 설명]
이 파일은 MCP 서버의 정식 출입구(프로세스 엔트리)다. `python -m crypto_deep_research.mcp_server`
로 실행되며, M5 패키징(docker-compose로 6개 프로그램 동시 가동)에서 이 경로가 쓰인다.
조립이 전부 "환경변수(env, 켤 때 바깥에서 꽂아주는 설정 쪽지)"로 결정된다는 점이 핵심:
견본↔CoinGecko 선택도, 문을 여는 주소도 코드 수정 없이 쪽지 두 장으로 끝난다.
server.py의 __main__ 블록과의 차이는 "env를 해석하느냐"다 — 환경 해석은 이 출입구 한 곳에
모으고, build_server는 받은 재료로 조립만 하는 순수 함수로 남긴다.
"""

import os

from crypto_deep_research.mcp_server.server import build_server
from crypto_deep_research.mcp_server.sources.coingecko import source_from_env

if __name__ == "__main__":
    # 환경변수 두 장으로 서버를 조립한다:
    #  - source_from_env(): COIN_DATA_SOURCE 쪽지를 읽어 견본/CoinGecko 출처를 고른다(기본=견본).
    #  - MCP_HOST: 문을 여는 주소(예: compose 안에서는 0.0.0.0). 없으면 None → SDK 기본(localhost).
    # M5 AC#2 "fixture->live 교체는 env-only"가 바로 이 한 줄로 구현된다.
    server = build_server(source_from_env(), host=os.environ.get("MCP_HOST"))
    # streamable HTTP = 누구나 주소만 알면 거는 "대표 전화" 방식. 워커 여럿이 동시에 붙어야
    # 하고 이 서버가 독립 프로세스/컨테이너이므로 1:1 전용인 stdio가 아니라 HTTP를 쓴다.
    server.run(transport="streamable-http")
