"""Process entry for one worker: ``python -m crypto_deep_research.serve_worker``.

Lives outside ``workers/`` on purpose: it's packaging, not agent code, so the M5 live
swap leaves ``workers/`` and ``orchestrator/`` byte-for-byte unchanged (AC#2). Env-driven
so a worker container is just an image + env: ``WORKER_KIND`` picks the worker, ``MCP_URL``
is the coin-data server, ``PUBLIC_URL`` is the worker's advertised A2A URL, ``PORT`` is the
bind port, ``MEMORY_DIR`` is where the worker opens its own checkpointer DB (A4). Adding a
worker = one registry entry here + a compose service.

[한글 설명]
워커 1개의 프로세스 정문(워커용 진입점). 항상 떠 있는 HTTP 서버로 기동한다.
왜 workers/ '밖'에 두나(M5 AC#2): 이건 '분석 코드'가 아니라 '포장(packaging)'이라서다. 정문·포트·
env 같은 배치 관심사가 workers/ 안에 섞이면 포장 작업마다 에이전트 코드에 수정 흔적(diff)이 남는다.
그래서 "어떻게 분석하는가"(workers/)와 "어떻게 켜져 있는가"(이 파일)를 폴더 수준에서 갈라, M5에서 샘플
데이터를 실데이터로 갈아끼우고 도커 포장을 해도 workers/·orchestrator/는 1바이트도 안 바뀐다.
워커 4종이 실행 파일·도커 이미지 하나를 공유한다 — 상자를 열 때 붙이는 메모 WORKER_KIND가
market이냐 sentiment냐에 따라 같은 설계도 4부가 서로 다른 워커가 된다(설계도 4개 따로 관리보다 훨씬 쌈).
"""

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import uvicorn
from starlette.applications import Starlette

from crypto_deep_research.contracts.artifact import Dimension
from crypto_deep_research.memory.working import worker_checkpointer, working_db_path
from crypto_deep_research.wiring import DEFAULT_MEMORY_DIR
from crypto_deep_research.workers.market.service import build_market_app
from crypto_deep_research.workers.onchain.service import build_onchain_app
from crypto_deep_research.workers.orderbook.service import build_orderbook_app
from crypto_deep_research.workers.sentiment.service import build_sentiment_app

# [한글] "WORKER_KIND 이름 → 그 워커 앱을 만드는 공장 함수"의 명부(registry).
#   if/elif 갈림길 대신 명부(dict)를 쓴 이유: 워커 추가 = 갈림길 로직 수정이 아니라 '명부에 한 줄 적기'.
#   wiring.py의 WORKER_URLS(지휘자 쪽 주소록)와 짝을 이루는 워커 쪽 명부다.
#   공장 함수 4개는 받는 재료가 똑같다((mcp_url, public_url, checkpointer)->Starlette) — 그래야 명부 방식이 성립.
_BUILDERS: dict[str, Callable[[str, str, Any], Starlette]] = {
    "market": build_market_app,
    "orderbook": build_orderbook_app,
    "sentiment": build_sentiment_app,
    "onchain": build_onchain_app,
}


# [한글] env 메모 3장으로 이 프로세스가 '어떤 워커'가 될지 정해 앱 객체를 만든다.
#   WORKER_KIND="나는 어떤 워커인가", MCP_URL="자료실(MCP 서버)은 어디인가", PUBLIC_URL=내 명함에
#   적을 '남에게 알려주는 내 주소'(밖에서 찾아오는 주소). 실제로 문 여는 bind 주소(0.0.0.0)와 다를 수 있다.
#   os.environ["..."] 직접 꺼내기 = 메모 없으면 그냥 KeyError로 죽는다. wiring의 친절한 _require와
#   결이 다른데 의도된 것: compose가 메모를 항상 채워주는 전제라, 정문 한 곳에 친절한 안내까지는 과잉.
#   build_app을 __main__ 밖 일반 함수로 뽑은 이유: 테스트(서버 안 띄우는 in-process E2E, 결정 T8)가
#   서버 기동 없이 앱 객체만 받아 검증할 수 있게.
def build_app(checkpointer: Any = None) -> Starlette:
    builder = _BUILDERS[os.environ["WORKER_KIND"]]
    return builder(os.environ["MCP_URL"], os.environ["PUBLIC_URL"], checkpointer)


# [한글] 실제로 워커 서버를 띄우는 구역(명령 실행 시에만 돈다).
if __name__ == "__main__":
    # cast(Dimension, ...): 환경변수 글자를 '분석 차원 이름'으로 간주하겠다는 타입 표시일 뿐 실제 검사는
    #   아니다. 틀린 값이면 어차피 build_app 안의 명부 조회 _BUILDERS[...]에서 KeyError로 죽으므로 검사 중복 안 함.
    dimension = cast(Dimension, os.environ["WORKER_KIND"])
    memory_dir = os.environ.get("MEMORY_DIR") or DEFAULT_MEMORY_DIR
    Path(memory_dir).mkdir(parents=True, exist_ok=True)
    # working_db_path(...) → .memory/working-market.db 식으로 워커마다 '자기 공책 파일'을 받는다(A4).
    #   워커 4명이 SQLite 공책 한 권을 동시에 쓰려 들면 펜 뺏기 싸움(잠금 경합)이 나므로 공책을 쪼개
    #   한 권당 펜잡이 1명으로 고정. 오케스트레이터의 orchestrator.db와 합치면 "DB 파일 1개 = 소유
    #   프로세스 1개" 전체 지형이 완성된다(test_db_topology가 자동 검증).
    # with worker_checkpointer(...): 들어갈 때 열고 나올 때 반드시 닫는 자동문 — 서버가 내려가면 DB
    #   연결도 같이 정리된다(수명 관리는 호출한 쪽 책임).
    with worker_checkpointer(working_db_path(memory_dir, dimension)) as cp:
        # host="0.0.0.0": compose 내부망의 오케스트레이터가 찾아오게 모든 문(네트워크 인터페이스)을 연다.
        #   단 리뷰 WC3 경고 — A2A 워커·MCP가 '무인증'으로 0.0.0.0 노출. 믿을 수 있는 내부망/내 컴퓨터
        #   안에서만 쓴다는 전제로는 의도된 설계이나, 외부 네트워크에 노출하면 누구나 analyze를 호출 가능.
        #   이 서버를 인터넷에 그대로 노출하면 안 된다.
        # port=int(os.environ["PORT"]): 포트=한 컴퓨터의 호실 번호. 같은 컴퓨터에 워커 4개를 띄우려면
        #   호실이 달라야 하므로 포트도 env 메모로 받는다(컨테이너 세계의 표준 관례).
        uvicorn.run(build_app(cp), host="0.0.0.0", port=int(os.environ["PORT"]))
