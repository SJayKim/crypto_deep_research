"""Static service wiring read from the environment.

Service URLs are required (no silent default); WORKER_TIMEOUT_S defaults to 30 (A3).
The worker registry is a data-driven, comma-separated URL list so adding a worker
never edits orchestrator/ code.

[한글 설명]
배선(wiring) = "어느 서비스가 서로 어디에 있는가"(URL·타임아웃·메모리 경로)를 env 메모에서 읽어
들이는 모듈. env(환경변수)는 프로그램을 켜기 전 책상에 적어 두는 설정 쪽지(.env)다.
정책 두 가지: (1) 주소(URL)는 '반드시' 적어야 하며 몰래 쓰는 기본값이 없다(없으면 시끄럽게 멈춘다,
M0 AC#5). (2) 타임아웃만 기본값 30초가 있다(A3의 env 쪽 절반).
워커 명단을 코드 분기문이 아니라 콤마로 이은 'URL 목록 데이터'로 둔다(data-driven 레지스트리) →
5번째 워커 추가가 코드 수정이 아니라 WORKER_URLS 쪽지에 주소 한 줄 덧붙이기로 끝나, orchestrator/를
건드리지 않는다. (워커 4개를 병렬 작업공간에서 동시 개발한 방식과도 맞물림 — 서로 충돌이 없게.)
"""

import os

from pydantic import BaseModel

# [한글] 기본 타임아웃 30초, 기본 메모리 폴더 ".memory"에 이름표를 붙여 둔 상수.
#   맨 숫자 30을 코드 곳곳에 흩뿌리는 대신 이름 있는 상수 하나로 모은다. 특히 DEFAULT_MEMORY_DIR는
#   serve_worker.py도 가져다 쓴다 → 두 파일이 서로 다른 기본 폴더를 쓰는 사고를 같은 이름표로 원천 차단.
DEFAULT_WORKER_TIMEOUT_S = 30
DEFAULT_MEMORY_DIR = ".memory"


# [한글] 읽어들인 배선 정보를 담는, 칸이 정해진 서류 양식(워커 주소 목록/MCP 주소/타임아웃/메모리 폴더).
#   CLAUDE.md 규약 "untyped dict 금지"대로, os.environ이라는 '아무 글자나 적힌 메모 더미'를 여기서
#   한 번 정식 서류로 옮겨 적으면, 이후 코드는 전부 칸·타입이 보장된 세계에서 논다. env를 읽는 행위가
#   코드 곳곳에 흩어지지 않고 이 모듈 한 곳에 모이는 것도 같은 효과.
class Wiring(BaseModel):
    worker_urls: list[str]
    mcp_url: str
    worker_timeout_s: int
    memory_dir: str


# [한글] 필수 메모 항목을 확인하고, 없으면 그 자리에서 멈추고 알려준다.
#   not value 조건은 '메모가 아예 없음'과 '항목 이름만 있고 내용이 빔(WORKER_URLS=)'을 똑같이 취급 —
#   둘 다 "주소를 안 적은" 같은 사고라서. 에러 메시지가 '고치는 방법까지'(.env에 적으세요, 예시는
#   .env.example) 알려줘, 프로젝트를 처음 받은 사람이 에러 화면만 보고 스스로 고칠 수 있게 한다.
def _require(var: str) -> str:
    value = os.environ.get(var)
    if not value:
        raise RuntimeError(f"required env var {var} is unset; set it in .env (see .env.example)")
    return value


# [한글] env 쪽지를 읽어 정식 Wiring 서류로 채워 돌려준다(시스템의 모든 배선 정보가 여기서 한 번 정해진다).
def load_wiring() -> Wiring:
    # 콤마로 이어 적은 주소 목록을 쪼개고, 양옆 공백을 다듬고, 빈 조각은 버린다 → "url1, url2,"처럼
    #   띄어쓰기·끝 콤마가 섞인 사람 손글씨 메모를 관대하게 받아준다.
    worker_urls = [u.strip() for u in _require("WORKER_URLS").split(",") if u.strip()]
    # 추가 검문: WORKER_URLS="," 같은 값은 첫 검문(_require)은 통과하지만(콤마라도 적혀 있으니) 다듬으면
    #   목록이 텅 빈다. 그 경우를 별도 메시지로 잡는다 — "메모 안 함"과 "메모는 했는데 내용 없음"은 다른 실수.
    if not worker_urls:
        raise RuntimeError("WORKER_URLS is set but contains no URLs")
    timeout_raw = os.environ.get("WORKER_TIMEOUT_S")
    # 필수/선택의 비대칭이 코드에 그대로 보인다: MCP_URL은 _require(없으면 즉시 정지), 타임아웃·메모리
    #   폴더는 안 적었으면 기본값으로. 구분 기준 — "없으면 동작 자체가 달라지는 것(주소)"은 필수,
    #   "없어도 누구나 수긍할 기본이 있는 것(제한 시간·저장 폴더)"은 선택.
    # int(timeout_raw): 타임아웃 칸에 숫자가 아닌 글자를 적으면 ValueError로 죽는다 — 잘못된 설정을 슬쩍
    #   눈감는 방어 코드를 일부러 안 넣었다(Simplicity First). 설정이 틀렸으면 조용히 넘기기보다 시끄럽게 죽는다.
    return Wiring(
        worker_urls=worker_urls,
        mcp_url=_require("MCP_URL"),
        worker_timeout_s=int(timeout_raw) if timeout_raw else DEFAULT_WORKER_TIMEOUT_S,
        memory_dir=os.environ.get("MEMORY_DIR") or DEFAULT_MEMORY_DIR,
    )
