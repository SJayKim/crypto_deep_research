"""Working memory: a worker's per-run scratchpad, durably backed by its own checkpointer DB.

The LangGraph checkpointer is the storage mechanism (DESIGN): the ``data -> work`` graph's
state IS the scratchpad -- ``data`` writes it, ``work`` reads it -- and the checkpointer
persists it. A4: each worker owns its own checkpointer DB file, distinct from the
orchestrator's episodic/long-term DB. The caller owns the checkpointer's lifetime.

[한글 설명]
작업 메모리(working) = 워커가 분석 1회를 도는 동안만 쓰는 "연습장". 게임 세이브 포인트처럼,
작업 그래프가 한 단계 진행될 때마다 현재 상태를 파일에 받아 적는다.
이 파일엔 클래스가 없다(결정 C2). 왜냐면 연습장의 본질은 이미 워커 그래프의 '상태(state)' 자체이기
때문 — data 노드(자료 수집)가 상태에 적고, work/distill 노드(요약)가 상태를 읽는 것이 곧 연습장
쓰기/읽기다. checkpointer는 그 상태를 꺼지지 않게 파일로 받아 적는 '저장 수단'일 뿐 기억 그 자체가
아니다. M0에서 정의한 note/read 약속(Protocol)은 안 쓰게 됐지만, 지우는 대신 이 사연을 설명문으로 남겼다.
따라서 이 모듈은 클래스 대신 함수 2개만 제공한다: 파일 경로 짓는 규칙 + checkpointer 여는 함수.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

# SqliteSaver: LangGraph가 주는 SQLite 기반 자동 저장 장치(checkpointer). 그래프가 한 단계
#   끝낼 때마다 상태 스냅샷(현재 상황 사진)을 DB 파일에 기록한다.
# Dimension: 워커 이름을 아무 글자나 받지 않고 미리 정한 4개("market" 등)만 허용하는 닫힌 목록.
#   "markets"(s 오타) 같은 실수를 mypy(실행 전 맞춤법 검사기)가 잡아 준다.
from crypto_deep_research.contracts.artifact import Dimension


# [한글] 이 워커의 공책(checkpointer DB) 파일 이름을 짓는 '작명 규칙'을 한 곳에 고정한다.
#   working-market.db, working-onchain.db ... 처럼 워커별로 파일이 갈린다(A4).
# 왜 함수로? 이 이름을 만드는 곳이 둘(실제 서버 기동 serve_worker.py, 배치도 테스트 test_db_topology)
#   이라, 규칙을 두 곳에 복사하면 한쪽만 바뀌었을 때 테스트가 엉뚱한 걸 검증한다. 함수 하나로 모은 것이
#   곧 A4의 "파일당 주인 1명" 규칙을 코드로 박아 둔 것. 결과를 Path가 아닌 str로 돌려주는 건
#   받는 쪽(SqliteSaver.from_conn_string)이 문자열을 원하기 때문.
def working_db_path(memory_dir: str, dimension: Dimension) -> str:
    """A worker's own checkpointer DB path (one file per worker, A4)."""
    return str(Path(memory_dir) / f"working-{dimension}.db")


# [한글] 워커의 checkpointer(자동 저장 장치)를 열어 주고, 다 쓰면 자동으로 닫아 준다.
#   @contextmanager + with = "빌려줬다가 끝나면 꼭 회수하는" 대여 장치. 공책을 반드시 덮는 것(연결
#   close)을 보장한다. "열기 + setup" 두 단계를 호출자마다 반복하지 않게 하는 최소 포장이라 클래스가
#   필요 없다(보관할 상태도 추가 동작도 없으니까).
@contextmanager
def worker_checkpointer(db_path: str) -> Iterator[SqliteSaver]:
    """Open a worker's own SQLite checkpointer at ``db_path`` (single-writer-per-file, A4)."""
    with SqliteSaver.from_conn_string(db_path) as saver:
        # 파일 경로로부터 SQLite 연결(공책 펼치기)과 saver를 만든다. 이것 자체가 대여 장치라 with로 감싼다.
        saver.setup()  # checkpointer가 쓸 표(양식 페이지)를 만든다. 멱등(여러 번 호출해도 안전).
        #   이걸 안 부르면 첫 저장 때 "no such table" 오류로 죽는다. 여는 함수가 setup까지 책임지므로
        #   호출자는 "펼치면 바로 쓸 수 있는" saver를 받는다.
        yield saver  # 호출자가 쓰는 동안 빌려주고, 작업이 끝나면 바깥 with가 정리한다.
        #   언제까지 쓸지(수명)는 여는 쪽(프로그램 시작점)의 책임 — 이 모듈은 '여는 방법'만 안다.
