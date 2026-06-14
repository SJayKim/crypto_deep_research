"""Episodic memory: past analyses per coin, in the orchestrator-owned SQLite DB.

Read trigger = run start retrieves the most recent run for a symbol (``last_for``); write
trigger = run end stores this run (``put``). One row per run; ``last_for`` orders by ts then
insertion order so same-second runs still resolve deterministically.

[한글 설명]
일화 기억(episodic) = "지난번에 이 코인 분석했을 때 결과가 이랬지"라는 일기장.
- 읽기 트리거: 분석 실행이 시작될 때 last_for(symbol)로 그 코인의 가장 최근 기록을 꺼낸다.
- 쓰기 트리거: 분석 실행이 끝날 때 put(record)으로 이번 기록을 한 줄 추가한다.
오케스트레이터(팀장)만 만진다 — 읽은 기록은 요약본으로 압축돼 워커에게 지시서로 전달되고, 워커는
일기장을 직접 펼치지 않는다(기억 소유권은 팀장에게 집중, 팀원은 stateless로 일한다).
longterm과 같은 orchestrator.db 파일을 공유한다(A4: 쓰는 사람이 같아 한 권에 동거).
"""

import sqlite3

from crypto_deep_research.contracts.memory import RunRecord
from crypto_deep_research.contracts.report import SynthesisReport


# [한글] EpisodicMemory 약속을 SQLite로 지키는 일기장 구현체.
#   Protocol을 '상속하지 않는다'는 점에 주목 — 파이썬 typing.Protocol은 혈통이 아니라 생김새(메서드
#   모양)로 판정하는 구조적 타이핑이다. last_for/put 모양만 맞으면 mypy가 "EpisodicMemory 자리에
#   들어갈 수 있다"고 인정한다. 족보로 엮지 않고 약속 준수만 검증받는 구조.
class SqliteEpisodicMemory:
    """``EpisodicMemory`` over SQLite (shares the orchestrator DB file with long-term)."""

    # [한글] 지정된 파일(공책)을 펼쳐 연결을 보관하고, runs 표가 없으면 만든다.
    #   생성자가 곧 마이그레이션: IF NOT EXISTS 덕분에 객체를 만들 때마다 표가 알아서 준비된다(멱등).
    #   별도 "DB 초기화 스크립트"가 필요 없다. ORM 없이 파이썬 기본 sqlite3 직접 사용 — 표 2~3개짜리
    #   저장소에 거대한 번역기(SQLAlchemy 등)는 과잉(Simplicity First).
    def __init__(self, db_path: str) -> None:
        # check_same_thread=False: sqlite3 기본 안전장치("공책 펼친 스레드만 쓸 수 있다")만 끈다.
        #   오케스트레이터는 asyncio라 작업이 스레드를 넘나들 수 있어서다. 동시에 여럿이 쓰겠다는 게
        #   아니라(쓰기는 어차피 오케스트레이터 한 흐름뿐) "펼친 사람만 써라" 검사만 푸는 것이라 안전.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        # runs 표 = 코인이름/시각/실행번호/보고서 네 칸. 한 행 = 분석 한 번(RunRecord와 1:1).
        #   PRIMARY KEY를 일부러 안 박았다(의도적 최소주의): 같은 run_id로 두 번 기록될 경로가 현재
        #   없고, 찾을 때는 코인 이름+시각으로만 찾는다. report 칸엔 최종 보고서를 JSON으로 통째로 넣는다.
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS runs "
            "(symbol TEXT NOT NULL, ts INTEGER NOT NULL, run_id TEXT NOT NULL, "
            "report TEXT NOT NULL)"
        )
        self._conn.commit()

    # [한글] 읽기 트리거: 이 코인의 기록 중 가장 최근 한 건을 꺼낸다(실행 시작 시 호출).
    def last_for(self, symbol: str) -> RunRecord | None:
        # ? = 파라미터 바인딩: 사용자가 준 글자(코인 이름)를 명령문에 직접 이어붙이지 않고 빈칸 양식에
        #   따로 끼워 넣는다 → 입력이 명령으로 둔갑하는 SQL injection 공격 차단.
        # ORDER BY ts DESC, rowid DESC = 이 파일에서 가장 섬세한 한 줄. ts(시각)는 초 단위라 같은
        #   1초 안에 두 실행이 끝나면 누가 '마지막'인지 모호하다. 그래서 SQLite가 모든 행에 몰래 매기는
        #   rowid(적힌 순서 일련번호)를 2차 기준으로 써서, 같은 초끼리도 나중에 적힌 쪽이 항상 이기게 했다
        #   → 테스트가 시계를 조작하지 않아도 결과가 오락가락(flaky)하지 않는다.
        # LIMIT 1 + fetchone(): 약속이 "마지막 하나"이므로 딱 하나만 가져온다.
        row = self._conn.execute(
            "SELECT run_id, symbol, ts, report FROM runs "
            "WHERE symbol = ? ORDER BY ts DESC, rowid DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        # None = 이 코인의 첫 분석. 오류가 아니라 평범한 값으로 처리 → 받는 쪽(app.py)은 "참고할 과거
        #   없음"으로 자연스럽게 이어간다.
        if row is None:
            return None
        # str()/int() 변환: DB에서 나온 행은 타입이 불분명한(Any) 묶음이라, 명시적 변환으로 mypy 통과 + 안전.
        # model_validate_json: 저장해 둔 JSON을 Pydantic 검증을 통과시켜 객체로 되살린다. 누가 DB를
        #   손으로 고쳤거나 옛 양식이면 여기서 시끄럽게 오류 → 조용히 깨진 데이터를 돌려주지 않는다.
        return RunRecord(
            run_id=str(row[0]),
            symbol=str(row[1]),
            ts=int(row[2]),
            report=SynthesisReport.model_validate_json(str(row[3])),
        )

    # [한글] 쓰기 트리거: 이번 실행 기록을 표에 한 줄 추가하고 즉시 확정 저장한다(실행 종료 시 호출).
    def put(self, record: RunRecord) -> None:
        # model_dump_json(): 보고서 객체 전체를 JSON 글자 하나로 포장해 한 칸에 넣는다. 보고서 속
        #   세부 항목을 칸칸이 펼치지(정규화) 않은 이유 — 일기장은 보고서를 '통째로 보관했다 통째로 꺼내는'
        #   용도라 세부 항목으로 검색·통계할 필요가 없다. 펼쳐 두면 보고서 양식이 바뀔 때마다 표까지 고쳐야 한다.
        self._conn.execute(
            "INSERT INTO runs (symbol, ts, run_id, report) VALUES (?, ?, ?, ?)",
            (record.symbol, record.ts, record.run_id, record.report.model_dump_json()),
        )
        # commit(): 확정 저장(연필 메모를 잉크로 굳히기). 실행 끝에 한 번만 부르니 모아서 저장할 필요가
        #   없고, 확정해 둬야 프로그램이 갑자기 죽어도 기록이 남는다.
        self._conn.commit()
