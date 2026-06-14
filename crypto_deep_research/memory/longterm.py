"""Long-term memory: user watchlist + learned coin facts, in the orchestrator-owned SQLite DB.

Read trigger = the planner reads ``watchlist``/``facts`` to choose the worker set (M3); write
trigger = run end appends newly learned facts (``add_facts``). Shares the single orchestrator
DB file with episodic memory (single-writer-per-file, A4).

[한글 설명]
장기 기억(long-term) = 오래 두고 참조하는 "관심 코인 목록 + 알게 된 사실 모음" 수첩.
세 층 중 유일하게 '읽기가 계획을 바꾼다': 플래너가 watchlist로 "추적 중인 코인인가"를, facts로
"쌓인 신호가 어느 분야를 가리키는가"를 판단해 어떤 워커들을 내보낼지 고른다(M3 fan-out).
- 읽기 트리거: 플래너가 watchlist/facts를 읽어 워커 집합 결정.
- 쓰기 트리거: 실행 종료 시 add_facts로 새로 알게 된 사실 추가.
episodic과 같은 orchestrator.db 파일을 공유한다(A4: 쓰는 사람=오케스트레이터가 같아 한 권에 동거).
삭제·수정 메서드가 없는 append-only(추가만, 지우개 없는 수첩) — 계약(contracts) 결정 그대로.
"""

import sqlite3


# [한글] LongTermMemory 약속을 SQLite로 지키는 수첩 구현체(episodic과 같은 약속 방식 — 구조적 타이핑).
class SqliteLongTermMemory:
    """``LongTermMemory`` over SQLite (shares the orchestrator DB file with episodic)."""

    # [한글] 공책을 펼치고, 관심목록 표와 사실 표가 없으면 만든다.
    #   episodic과 '같은 db_path(같은 공책 파일)'를 받는 것이 A4의 후반부: runs/watchlist/facts 표가
    #   한 권의 orchestrator.db에 동거한다. 쓰는 사람이 오케스트레이터 하나뿐이라 공책을 더 쪼갤 이유가 없다.
    def __init__(self, db_path: str) -> None:
        # check_same_thread=False: episodic과 동일 이유(asyncio가 스레드를 넘나듦). 정보성 발견 Mem4 —
        #   episodic과 longterm이 같은 파일을 '각자 따로' 펼친다(연결 공유 없음, WAL 미설정). 지금은
        #   펼치는 주체가 오케스트레이터 하나뿐이라 무해. 동시성을 늘리면 연결 공유나 WAL을 켜라는 메모만 남겼다.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        # watchlist는 symbol PRIMARY KEY: 관심목록은 집합(같은 코인이 두 번 들어갈 의미 없음)이라
        #   DB 차원에서 중복을 막는다.
        self._conn.execute("CREATE TABLE IF NOT EXISTS watchlist (symbol TEXT PRIMARY KEY)")
        # facts엔 PRIMARY KEY 없음: 한 코인에 사실이 여러 개인 게 정상이라 평범한 (코인, 사실) 행.
        #   중복 방지는 아래 add_facts가 프로그램 쪽에서 처리한다.
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS facts (symbol TEXT NOT NULL, fact TEXT NOT NULL)"
        )
        self._conn.commit()

    # [한글] 읽기 트리거(1): 관심목록 전체를 평범한 글자 목록으로 돌려준다(플래너가 호출).
    #   DB 전용 객체(행/커서)를 밖으로 내보내지 않고 순수 파이썬 값으로 변환 → 받는 쪽(플래너)은
    #   뒤에 SQLite가 있다는 사실조차 모른다(Protocol이 약속한 모양 그대로).
    #   watchlist에 '추가하는 메서드가 없다'는 점도 의도적 — 현재 단계에선 관심목록은 사용자가 미리
    #   넣어 두는 데이터이고, 시스템이 스스로 목록을 바꾸는 트리거가 없다. 트리거 없는 기능은 안 만든다.
    def watchlist(self) -> list[str]:
        rows = self._conn.execute("SELECT symbol FROM watchlist").fetchall()
        return [str(row[0]) for row in rows]

    # [한글] 읽기 트리거(2): 해당 코인의 사실 전체를 글자 목록으로 돌려준다. ?로 안전하게 끼워 넣음.
    def facts(self, symbol: str) -> list[str]:
        rows = self._conn.execute("SELECT fact FROM facts WHERE symbol = ?", (symbol,)).fetchall()
        return [str(row[0]) for row in rows]

    # [한글] 쓰기 트리거: 들어온 사실들 중 '처음 보는 것만' 골라 표에 추가한다(실행 종료 시 호출).
    #   이미 아는 사실을 또 안 적는 것 = dedup(중복 제거). 리뷰 발견 O2의 수정 결과:
    #   원래는 무조건 추가였는데, 같은 코인을 반복 분석하면 비슷한 key_points가 매번 다시 들어와 수첩이
    #   부풀고, 그 부푼 수첩에서 단서를 찾는 플래너 판단이 흐려졌다 → "반복해도 facts 행이 무한히 안 늚"이 합격 기준.
    #   왜 DB의 UNIQUE 제약이 아니라 파이썬 dedup? 기존 표 구조를 안 바꾸는(마이그레이션 불필요) 최소
    #   변경이고, 쓰는 사람이 하나뿐이라 "읽고 나서 쓰는 사이"에 끼어들 경쟁자가 없어 정확성도 동일하기 때문.
    def add_facts(self, symbol: str, facts: list[str]) -> None:
        # dedup 1겹: 수첩에 '이미 있는' 사실과의 중복을 거른다.
        known = set(self.facts(symbol))
        new_facts: list[str] = []
        for fact in facts:
            if fact not in known:
                known.add(fact)  # dedup 2겹: 이번에 들어온 묶음 안의 중복(["dup","dup","x"])까지 거른다.
                new_facts.append(fact)  # 이 2겹을 빼먹으면 한 호출 안의 중복이 그대로 들어간다(테스트가 겨눔).
        # executemany + 마지막 1회 commit: 새 사실 N개를 한 거래로 묶어 추가. new_facts가 비면(실패한
        #   실행이라 key_points가 없을 때 등) executemany는 자연히 아무것도 안 함 → 빈 목록용 분기를 따로
        #   짜지 않았다(무해한 시나리오용 방어 코드 금지).
        self._conn.executemany(
            "INSERT INTO facts (symbol, fact) VALUES (?, ?)",
            [(symbol, fact) for fact in new_facts],
        )
        self._conn.commit()
