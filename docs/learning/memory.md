# 학습 자료: `memory/` 패키지 — 3층 메모리 구현체 완전 해부 (쉬운 설명판)

> 대상: `crypto_deep_research/memory/` 의 3개 모듈 (`working.py`, `episodic.py`, `longterm.py`).
> 목적: 각 코드가 **무슨 의미**인지, **무슨 기능**인지, **왜 이렇게 설계했는지**를 한 줄 단위로, 개발 지식이 없어도 따라올 수 있게 풀어 쓴다.
> 설계 결정 코드(A4, C2, TENSION-B, O2, Mem4, W2)의 원 출처는 [docs/DESIGN.md](../DESIGN.md)의 결정 테이블과 [docs/reviews/05-memory.md](../reviews/05-memory.md). 결정 코드는 "이 선택을 왜 했는지"를 기록해 둔 회의록의 항목 번호라고 생각하면 된다.
> 메모리의 **인터페이스**(`WorkingMemory`/`EpisodicMemory`/`LongTermMemory` Protocol, `RunRecord`)는 [contracts.md](./contracts.md) §5에서 다뤘다. 인터페이스가 "약속한 기능 목록"이라면, 이 문서는 그 약속을 **실제로 지키는 코드** — 어떤 파일에 어떻게 저장하는지 — 에 집중한다.

---

## 0. 큰 그림: 3층 메모리와 DB 토폴로지 (설계 결정 A4)

먼저 용어 하나. **DB(데이터베이스)** 는 프로그램이 정보를 적어 두는 "공책"이고, 이 프로젝트에서는 **SQLite**라는 방식을 쓴다. SQLite는 서버 컴퓨터를 따로 두지 않고 그냥 파일 하나가 곧 공책이 되는, 가장 단순한 종류의 데이터베이스다. "DB 토폴로지"란 그 공책들을 몇 권 만들고 누가 어느 공책에 쓰게 할지의 **배치도**다.

이 시스템의 기억은 사람처럼 3층이다:
- **Working(작업 기억)** = 일하는 동안만 쓰는 "연습장". 계산 중간 과정 메모.
- **Episodic(일화 기억)** = "지난번에 이 코인 분석했을 때 결과가 이랬지"라는 일기장.
- **Long-term(장기 기억)** = 오래 두고 참조하는 "관심 목록 + 알게 된 사실 모음" 수첩.

DESIGN.md의 전제 5: **"트리거 없는 메모리 층은 장식이다."** 즉, 실제로 누군가 읽고 쓰는 순간(트리거)이 없는 기억 장치는 만들 필요가 없다. 세 층 각각에 실제로 읽고 쓰는 지점이 시스템 안에 존재해야 한다.

| 층 | 구현 파일 | 저장소 | 읽기 트리거 | 쓰기 트리거 |
|---|---|---|---|---|
| Working | `working.py` | 워커별 `working-<dim>.db` (LangGraph checkpointer) | distill(work) 노드가 스크래치패드를 읽음 | data 노드가 중간 결과를 기록 |
| Episodic | `episodic.py` | `orchestrator.db` | 실행 시작 시 `last_for(symbol)` | 실행 종료 시 `put(record)` |
| Long-term | `longterm.py` | `orchestrator.db` (episodic과 공유) | 플래너가 `watchlist`/`facts` 읽고 워커 집합 결정 | 실행 종료 시 `add_facts` |

(표의 등장인물: **오케스트레이터** = 전체 작업을 지휘하는 팀장 프로그램, **워커** = 시세·오더북·여론·온체인 4개 분야를 하나씩 맡은 팀원 프로그램, **플래너** = 이번에 어떤 워커들을 내보낼지 정하는 계획 담당.)

파일 토폴로지(공책 배치도)를 그림으로:

```
<memory_dir>/
├── orchestrator.db        ← 오케스트레이터만 쓴다 (episodic + long-term 테이블 동거)
├── working-market.db      ← market 워커만 쓴다 (LangGraph checkpointer)
├── working-orderbook.db   ← orderbook 워커만 쓴다
├── working-sentiment.db   ← sentiment 워커만 쓴다
└── working-onchain.db     ← onchain 워커만 쓴다
```

**왜 이렇게? → 설계 결정 A4**: "각 워커는 자기 checkpointer DB를 소유하고, 오케스트레이터가 episodic + long-term DB를 단독 소유한다 (single-writer-per-file). MCP 서버는 stateless."

핵심은 **공책 한 권당 펜을 쥔 사람이 한 명**(single writer per file)이라는 것. 이 시스템은 6개의 독립 프로그램(프로세스)이 동시에 돌아가는데, SQLite는 여러 프로그램이 한 파일에 **동시에 쓰려고 하면** 약하다 — 두 사람이 한 공책에 동시에 쓰려다 서로 손을 밀치는 상황("파일 잠금 경합", `database is locked` 오류)이 생긴다. 공책을 주인별로 한 권씩 나눠주면 이 문제가 **구조적으로** 사라진다 — "손 안 부딪히게 조심하는 규칙"을 만드는 게 아니라, 애초에 부딪힐 수 없는 자리 배치를 고른 것이다. 또한 `test_db_topology`라는 테스트가 확인하듯, 워커 공책과 오케스트레이터 공책의 분리는 **컨텍스트 격리(서로의 머릿속을 안 들여다보게 하기)의 저장소 버전**이기도 하다: 워커의 중간 메모가 오케스트레이터 공책으로 새어 들어갈 통로 자체가 없다.

**왜 메모리가 "서비스"가 아니라 "라이브러리 + SQLite"인가?** 서비스란 메모리 전담 직원(별도 프로그램)을 한 명 더 고용하는 것이고, 라이브러리는 각자 책상 서랍에 공책을 두는 것이다. DESIGN.md의 결정: "Memory as service vs library: library + DB(SQLite로 시작)를 추천 — 움직이는 부품을 하나 줄인다. wire-실재성이 필요한 개념은 MCP와 A2A이지 메모리가 아니다." 이 프로젝트의 학습 목표는 프로그램들 사이의 통신 규약(MCP/A2A — 직원들 사이의 공식 문서 양식이라 보면 된다)이고, 메모리는 그 목표를 돕는 부품일 뿐이므로 가장 단순한 형태(같은 프로그램 안에서 직접 여는 SQLite 파일)로 둔다.

또 하나의 일정 결정 — **TENSION-B**: 메모리 전체를 뒤 단계(M4)로 미루지 않고, long-term의 **읽기** 트리거(플래너가 워커 집합을 고르는 것)만큼은 핵심 기능(M3 fan-out)과 함께 먼저 내놨다. 읽기 트리거가 "팀을 어떻게 굴릴지"의 모양을 결정하므로, 핵심 단계에서 실제로 작동시켜 봐야지 맨 끝에 장식처럼 덧붙이면 안 된다는 이유다.

---

## 1. `working.py` — 작업 메모리: "checkpointer가 곧 저장소" (결정 C2)

**checkpointer**란 LangGraph(워커의 작업 절차를 그래프로 짜 주는 도구)에 딸린 "자동 저장" 장치다. 게임의 세이브 포인트처럼, 작업이 한 단계 진행될 때마다 현재 상태를 파일에 받아 적는다.

### 배경: 왜 이 파일엔 클래스가 없나

contracts.md §5에서 본 대로, `WorkingMemory` Protocol(`note`/`read` — "메모해라/읽어라"라는 약속)의 구현 클래스는 **존재하지 않는다**. M0 단계에서 약속(계약)을 먼저 정의했지만, 실제로 만들 때 보니 작업 메모리의 본질이 "워커 그래프의 상태(state) 그 자체"였다: `data` 노드(자료 수집 단계)가 상태에 적고 `work`(distill, 요약 단계) 노드가 상태를 읽는 것이 이미 연습장의 쓰기/읽기다. checkpointer는 그 상태를 **꺼지지 않게 파일로 받아 적는 장치**일 뿐이다 — DESIGN.md의 표현으로 "the checkpointer is the storage mechanism, not the memory itself"(checkpointer는 저장 수단이지 기억 그 자체가 아니다).

리뷰에서 이 "약속은 있는데 구현이 다른 모양" 불일치가 **C2** 이슈로 기록됐고, 결정은 "Protocol(약속)을 지우지 않고 docstring(코드 안 설명문)으로 사실을 명시"였다 (05-memory.md: "working layer = checkpointer(state-as-scratchpad), note/read protocol 미사용"). 그래서 이 파일은 클래스 대신 **함수 2개**만 제공한다: 파일 경로 짓는 규칙과, checkpointer를 열어 주는 함수.

### 줄별 해설

```python
from langgraph.checkpoint.sqlite import SqliteSaver

from crypto_deep_research.contracts.artifact import Dimension
```
- 이 코드는 "필요한 부품 두 개를 가져온다"는 뜻이다.
- `SqliteSaver`: LangGraph가 제공하는 SQLite 기반 checkpointer. 그래프가 작업 단계를 하나 끝낼 때마다 상태 스냅샷(현재 상황 사진)을 DB 파일에 기록한다.
- `Dimension`을 가져오는 이유: 워커 이름을 아무 글자나 받지 않고, 미리 정해 둔 4개("market" 등)만 허용하는 닫힌 목록으로 받는다. `working_db_path(dir, "markets")` 같은 오타(s가 붙음)를 mypy(코드를 실행 전에 검사해 주는 맞춤법 검사기 같은 도구)가 잡아 준다.

```python
def working_db_path(memory_dir: str, dimension: Dimension) -> str:
    """A worker's own checkpointer DB path (one file per worker, A4)."""
    return str(Path(memory_dir) / f"working-{dimension}.db")
```
- 이 코드는 "이 워커의 공책 파일 이름은 이렇게 짓는다"는 작명 규칙을 한 곳에 고정한다는 뜻이다. `working-market.db`, `working-onchain.db`...
- **왜 함수로 뺐나?**: 이 이름을 만드는 곳이 둘이다 — 실제 서버 가동(`serve_worker.py:44`)과 배치도 테스트(`test_db_topology.py`). 규칙을 두 곳에 복사해 두면 한쪽만 바뀌었을 때 테스트가 엉뚱한 것을 검증하게 된다. 함수 하나로 모아 둔 것이 곧 A4의 "파일당 주인 1명" 규칙을 코드로 박아 둔 것이다.
- 결과를 `Path`(경로 전용 타입)가 아니라 평범한 문자열(`str`)로 돌려주는 것은, 받는 쪽(`SqliteSaver.from_conn_string`)이 문자열을 원하기 때문 — 건네받는 쪽이 원하는 형태로 맞춰서 내보낸다.

```python
@contextmanager
def worker_checkpointer(db_path: str) -> Iterator[SqliteSaver]:
    """Open a worker's own SQLite checkpointer at ``db_path`` (single-writer-per-file, A4)."""
    with SqliteSaver.from_conn_string(db_path) as saver:
        saver.setup()
        yield saver
```
- 이 코드는 "워커의 checkpointer(자동 저장 장치)를 열어 주고, 다 쓰면 자동으로 닫아 준다"는 뜻이다. context manager란 "빌려줬다가 끝나면 꼭 회수하는" 파이썬의 대여 장치다.
- `SqliteSaver.from_conn_string(db_path)`: 파일 경로로부터 SQLite 연결(공책을 펼치는 것)과 saver를 만든다. 이것 자체가 대여 장치라 `with`로 감싼다 — 공책을 반드시 덮는 것(연결 close)을 보장.
- `saver.setup()`: checkpointer가 쓸 표(테이블 — 공책 안의 양식 페이지)를 만든다. 몇 번 불러도 안전(멱등). 이걸 안 부르면 첫 저장 시도에서 "no such table"(그런 양식 페이지가 없음) 오류로 죽는다. **여는 함수가 setup까지 책임지므로** 호출자는 "펼치면 바로 쓸 수 있는" saver를 받는다.
- `yield saver`: 호출자가 쓰는 동안 saver를 빌려주고, 호출자 작업이 끝나면 바깥 `with`가 정리한다. docstring의 "The caller owns the checkpointer's lifetime"(수명 관리는 빌려간 쪽 책임)이 이 구조의 의미다 — 언제까지 쓸지는 여는 쪽(프로그램 시작점)의 일이고, 이 모듈은 여는 방법만 안다.
- **왜 한 번 더 감쌌나?** "열기 + setup" 두 단계를 호출자마다 반복하지 않게 하는 최소한의 포장이다. 클래스를 만들 이유가 없다 — 보관할 상태도 추가 동작도 없으니까.

### 라이브 연결: 누가 이걸 쓰나

```python
# serve_worker.py (워커 프로세스 entry)
with worker_checkpointer(working_db_path(memory_dir, dimension)) as cp:
    uvicorn.run(build_app(cp), host="0.0.0.0", port=int(os.environ["PORT"]))
```
- 이 코드는 "워커 프로그램이 켜질 때 **자기** 공책을 펼치고, 서버가 살아 있는 동안 자동 저장 장치도 함께 살아 있다"는 뜻이다. 공책을 둘 폴더는 `MEMORY_DIR`라는 환경 설정값으로 받으므로, 컨테이너(격리된 실행 상자)에서는 폴더 하나만 연결해 주면 끝난다.

```python
# workers/base.py
graph.compile(checkpointer=checkpointer)
config = {"configurable": {"thread_id": run_id}} if checkpointer is not None else None
```
- 이 코드는 "작업 그래프를 조립할 때 자동 저장 장치를 끼우면, 단계마다 상태가 저장된다"는 뜻이다. `thread_id=run_id`: 저장 기록을 **실행 1회 단위로 묶는 꼬리표**로, 팀 통신(A2A)에서 쓰던 실행 번호(`run_id`)를 그대로 재사용한다 — "실행마다 새 연습장(per-run scratchpad)"이 여기서 실현된다.
- `checkpointer=None`이면 설정도 없음 — 테스트에서는 자동 저장 없이 그래프를 돌릴 수 있게 한 선택 사항. 리뷰 W2가 지적했던 "장치는 만들어 놨는데 실제 가동 라인에는 연결 안 됨" 상태를 `serve_worker.py`에서 연결함으로써 해소한 결과다.

---

## 2. `episodic.py` — 에피소드 메모리: "지난번 이 코인 분석"

### 배경

`EpisodicMemory` Protocol(읽기 = 실행 시작 시 `last_for`("이 코인의 마지막 기록 줘"), 쓰기 = 실행 종료 시 `put`("이번 기록 넣어"))의 SQLite 구현, 즉 일기장이다. 오케스트레이터(팀장)만 만지며(`orchestrator/app.py:84,98`), 읽은 기록은 요약본(`episodic_seed`)으로 압축되어 작업 지시서(A2A `TaskParams`)에 실려 워커에게 전달된다 — 워커는 일기장을 직접 펼치지 않는다(기억의 소유권은 팀장에게 집중, 팀원은 기억 없이(stateless) 일한다).

### 줄별 해설

```python
class SqliteEpisodicMemory:
    """``EpisodicMemory`` over SQLite (shares the orchestrator DB file with long-term)."""
```
- Protocol을 **상속하지 않는다**(약속 문서에 도장을 찍어 묶이지 않는다)는 점에 주목. 파이썬의 `typing.Protocol`은 "구조적 타이핑" — 혈통이 아니라 생김새로 판정한다. `last_for`/`put`이라는 메서드의 모양만 맞으면, mypy가 "이 클래스는 `EpisodicMemory` 자리에 들어갈 수 있다"고 검사해 준다. 족보로 엮이지 않고 약속 준수만 검증받는 구조.

```python
    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
```
- 이 코드는 "지정된 파일(공책)을 펼쳐서 연결을 보관한다"는 뜻이다.
- 파이썬 기본 제공 `sqlite3`를 직접 사용 — ORM(DB를 다뤄 주는 큰 중간 번역기, 예: SQLAlchemy) 없음. 표 2~3개, 질의 5개짜리 저장소에 거대한 번역기를 들이는 건 과잉이다(Simplicity First).
- `check_same_thread=False`: sqlite3의 기본 안전장치는 "공책을 펼친 스레드(프로그램 안의 작업 흐름)만 그 공책을 쓸 수 있다"인데, 오케스트레이터는 asyncio(여러 일을 번갈아 처리하는 방식) 기반이라 작업이 스레드를 넘나들 수 있어 이 검사만 끈다. 동시에 여럿이 쓰겠다는 게 아니라(쓰기는 어차피 오케스트레이터 한 흐름뿐) "펼친 사람만 써라" 검사만 푸는 것이므로 안전하다.

```python
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS runs "
            "(symbol TEXT NOT NULL, ts INTEGER NOT NULL, run_id TEXT NOT NULL, "
            "report TEXT NOT NULL)"
        )
        self._conn.commit()
```
- 이 코드는 "runs라는 표(코인 이름, 시각, 실행 번호, 보고서 네 칸짜리)가 없으면 만든다"는 뜻이다.
- **생성자가 곧 마이그레이션**: 보통 DB는 별도의 "초기 설치 절차"가 필요한데, 여기선 `IF NOT EXISTS`(이미 있으면 건너뜀) 덕분에 객체를 만들 때마다 표가 알아서 준비된다 — 몇 번을 실행해도 안전(멱등)하고, 별도 "DB 초기화 스크립트"가 필요 없다.
- 표의 한 행 = 분석 한 번(`RunRecord`와 1:1). `report TEXT` 칸에는 최종 보고서(`SynthesisReport`)를 JSON(데이터를 글자로 직렬화한 표준 포장 형식)으로 통째로 넣는다 — 아래 참조.
- PRIMARY KEY(중복을 금지하는 대표 칸)가 없다: `run_id`를 대표 칸으로 안 박은 건 의도적 최소주의로 읽힌다. 같은 실행 번호로 두 번 기록될 시나리오가 현재 코드 경로에 없고, 찾을 때는 코인 이름+시각으로만 찾는다.

```python
    def last_for(self, symbol: str) -> RunRecord | None:
        row = self._conn.execute(
            "SELECT run_id, symbol, ts, report FROM runs "
            "WHERE symbol = ? ORDER BY ts DESC, rowid DESC LIMIT 1",
            (symbol,),
        ).fetchone()
```
- 이 코드는 "이 코인의 기록 중 가장 최근 한 건을 꺼낸다"는 뜻이다.
- `?` 는 **파라미터 바인딩**: 사용자가 준 글자(코인 이름)를 명령문에 직접 이어붙이지 않고, 빈칸 양식에 별도로 끼워 넣는 방식이다. 이래야 악의적인 입력이 명령으로 둔갑하는 공격(SQL injection — 입력란에 명령을 써넣어 DB를 조종하는 수법)이 차단된다. 리뷰 ③보안 항목에서 확인된 사항.
- **`ORDER BY ts DESC, rowid DESC`가 이 파일에서 가장 섬세한 한 줄**: `ts`(시각)는 초 단위 정수라, 같은 1초 안에 두 실행이 끝나면 시각만으로는 어느 게 "마지막"인지 모호하다. 그래서 SQLite가 모든 행에 몰래 매겨 두는 `rowid`(적힌 순서대로 커지는 일련번호)를 2차 정렬 기준으로 써서, **같은 초의 실행끼리도 항상** 나중에 적힌 쪽이 이기게 했다. 모듈 docstring이 이를 약속으로 명시: "same-second runs still resolve deterministically"(같은 초의 실행도 결정적으로 판가름난다). 덕분에 테스트가 시계를 조작하지 않아도 결과가 오락가락(flaky)하지 않는다.
- `LIMIT 1` + `fetchone()`: 약속이 "마지막 하나"이므로 딱 하나만 가져온다 — 그 이상 가져오지 않는다.

```python
        if row is None:
            return None
        return RunRecord(
            run_id=str(row[0]),
            symbol=str(row[1]),
            ts=int(row[2]),
            report=SynthesisReport.model_validate_json(str(row[3])),
        )
```
- 이 코드는 "기록이 없으면 '없음'을 돌려주고, 있으면 검사를 거쳐 객체로 되살린다"는 뜻이다.
- `None` = 이 코인의 첫 분석. 오류(예외)가 아니라 평범한 값으로 처리 — 받는 쪽(`app.py`)은 "참고할 과거 없음"으로 자연스럽게 이어간다.
- `str()`/`int()` 변환: DB에서 나온 행은 타입이 불분명한(`Any`) 묶음이라, 명시적 변환으로 mypy 검사 통과 + 안전장치를 겸한다.
- `SynthesisReport.model_validate_json`: 저장해 둔 JSON을 **Pydantic(데이터가 정해진 양식에 맞는지 검사해 주는 도구)의 검증을 통과시켜** 되살린다. 누가 DB 파일을 손으로 고쳤거나 옛 버전 양식이면 여기서 시끄럽게 오류가 난다 — 조용히 깨진 데이터를 돌려주지 않는다. 리뷰는 이를 "내부 데이터라 믿을 만하지만, 그래도 꺼낼 때 양식 검증"으로 평가했다.

```python
    def put(self, record: RunRecord) -> None:
        self._conn.execute(
            "INSERT INTO runs (symbol, ts, run_id, report) VALUES (?, ?, ?, ?)",
            (record.symbol, record.ts, record.run_id, record.report.model_dump_json()),
        )
        self._conn.commit()
```
- 이 코드는 "이번 실행 기록을 표에 한 줄 추가하고, 즉시 확정 저장한다"는 뜻이다.
- `model_dump_json()`: 보고서 객체 전체를 JSON 글자 하나로 포장해 한 칸에 넣는다. **왜 보고서 내부 항목을 칸칸이 펼치지 않았나?** 일기장은 보고서를 "통째로 보관했다가 통째로 꺼내는" 용도다 — 보고서 속 세부 항목으로 검색하거나 통계 낼 필요가 없다. 필요 없는 칸 나누기(정규화)는 나중에 보고서 양식이 바뀔 때 표까지 고쳐야 하는 비용만 키운다. (보고서 양식이 바뀌어도 표는 그대로.)
- 매 `put`마다 `commit()`(확정 저장 — 연필 메모를 잉크로 굳히는 것): 실행 끝에 한 번만 부르니 모아서 저장할 필요가 없고, 확정해 둬야 프로그램이 갑자기 죽어도 기록이 남는다.

---

## 3. `longterm.py` — 장기 메모리: 관심목록 + 누적 사실

### 배경

`LongTermMemory` Protocol의 SQLite 구현 — 관심 코인 목록과, 분석하며 알게 된 사실들을 모아 두는 수첩이다. 세 층 중 유일하게 **읽기가 계획을 바꾼다**: 플래너(`orchestrator/planner.py`)가 `watchlist`로 "추적 중인 코인인가"를, `facts`로 "쌓인 신호가 어느 분야를 가리키는가"를 판단해 어떤 워커들을 내보낼지 고른다. DESIGN.md의 성공 기준 그대로 — "watchlist/facts가 계획을 바꾼다(long-term)."

### 줄별 해설

```python
    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("CREATE TABLE IF NOT EXISTS watchlist (symbol TEXT PRIMARY KEY)")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS facts (symbol TEXT NOT NULL, fact TEXT NOT NULL)"
        )
        self._conn.commit()
```
- 이 코드는 "공책을 펼치고, 관심목록 표와 사실 표가 없으면 만든다"는 뜻이다.
- episodic과 **같은 `db_path`(같은 공책 파일)** 를 받는 것이 A4의 후반부: 일기장의 `runs` 표, 수첩의 `watchlist`/`facts` 표가 한 권의 `orchestrator.db`에 동거한다. 이 공책에 쓰는 사람이 오케스트레이터 하나뿐이므로 공책을 더 쪼갤 이유가 없다 — 공책을 나누는 기준은 "기억의 층"이 아니라 **"누가 쓰는가(writer)"** 다.
- `watchlist`는 `symbol TEXT PRIMARY KEY`: 관심목록은 집합(같은 항목이 두 번 있을 수 없는 명단)이다 — 같은 코인이 두 번 들어갈 의미가 없으니, PRIMARY KEY(대표 칸)가 DB 차원에서 중복을 막는다.
- `facts`엔 PRIMARY KEY가 없다: 한 코인에 사실이 여러 개인 게 정상이므로 평범한 (코인, 사실) 행. 중복 방지는 아래 `add_facts`가 프로그램 쪽에서 처리한다.

```python
    def watchlist(self) -> list[str]:
        rows = self._conn.execute("SELECT symbol FROM watchlist").fetchall()
        return [str(row[0]) for row in rows]

    def facts(self, symbol: str) -> list[str]:
        rows = self._conn.execute("SELECT fact FROM facts WHERE symbol = ?", (symbol,)).fetchall()
        return [str(row[0]) for row in rows]
```
- 이 코드는 "관심목록 전체 / 해당 코인의 사실 전체를 꺼내서, 평범한 글자 목록으로 돌려준다"는 뜻이다.
- 둘 다 단순 조회. DB 전용 객체(행, 커서)를 밖으로 내보내지 않고 **순수 파이썬 값으로 변환해서** 반환 — 받는 쪽(플래너)은 뒤에 SQLite가 있다는 사실조차 모른다. Protocol이 약속한 모양 그대로.
- watchlist에 **추가하는 메서드가 없다**는 것도 눈여겨볼 점: 현재 단계에서 관심목록은 사용자가 미리 넣어 두는 데이터(테스트/초기 세팅에서 직접 INSERT)이고, 시스템이 돌아가다가 스스로 목록을 바꾸는 요구가 없다. 인터페이스는 실제 트리거(쓰는 순간)가 있는 것만 담는다 — "언젠가 필요할지도" 기능은 안 만든다.

```python
    def add_facts(self, symbol: str, facts: list[str]) -> None:
        known = set(self.facts(symbol))
        new_facts: list[str] = []
        for fact in facts:
            if fact not in known:
                known.add(fact)
                new_facts.append(fact)
        self._conn.executemany(
            "INSERT INTO facts (symbol, fact) VALUES (?, ?)",
            [(symbol, fact) for fact in new_facts],
        )
        self._conn.commit()
```
- 이 코드는 "들어온 사실들 중 처음 보는 것만 골라서 표에 추가한다"는 뜻이다. 이미 아는 사실을 또 적지 않는 것을 **dedup**(deduplication, 중복 제거)이라 한다.
- **이 dedup 로직은 리뷰 발견 O2(저장측)의 수정 결과다.** 원래는 무조건 추가였는데, 리뷰가 지적했다: "`add_facts`가 dedup/상한 없이 무제한 적재 → 누적 시 `plan_dimensions` 부분문자열 매칭 신호 퇴화." 풀어 말하면: 같은 코인을 반복 분석하면 비슷한 핵심 요점(key_points)이 매번 다시 들어와 수첩이 같은 문장으로 부풀고, 그 부푼 수첩에서 단서를 찾는 플래너의 판단이 흐려진다. 수정의 합격 기준은 "같은 실행을 반복해도 facts 행 수가 무한히 늘지 않음" — `tests/test_longterm_memory.py`의 두 테스트가 그것이다.
- dedup이 **두 겹**이다: `known = set(self.facts(symbol))`이 **수첩에 이미 있는 것**과의 중복을 거르고, 반복문 안의 `known.add(fact)`가 **이번에 들어온 묶음 안의** 중복(`["dup", "dup", "unique"]` 같은)까지 거른다. 후자를 빼먹으면 한 번의 호출 안에 든 중복이 그대로 들어간다 — 테스트 `test_add_facts_dedups_within_batch`가 정확히 이 구멍을 겨눈다.
- **왜 DB의 중복 금지 기능(unique 제약)이 아니라 파이썬 dedup인가?** `UNIQUE(symbol, fact)` + `INSERT OR IGNORE`("중복이면 조용히 버려라")로도 가능했다. 파이썬 쪽을 고른 것은 이미 만들어진 표의 구조를 안 바꾸는(마이그레이션 — 기존 표를 새 양식으로 개조하는 작업 — 이 필요 없는) 최소 변경이고, 쓰는 사람이 하나뿐이라 "읽고 나서 쓰는 사이"에 끼어들 경쟁자가 없어 정확성도 동일하기 때문으로 읽힌다.
- `executemany` + 마지막 1회 `commit`: 새 사실 N개를 한 번의 거래(트랜잭션)로 묶어 추가. `new_facts`가 비어 있으면(실패한 실행이라 핵심 요점이 없을 때 등) `executemany`는 자연히 아무것도 안 함 — 빈 목록용 분기를 따로 짜지 않았다(일어나지 않거나 무해한 시나리오용 방어 코드 금지).
- 삭제·수정 메서드가 없는 append-only(추가만 가능, 지우개 없는 수첩)인 것은 contracts.md §5에서 본 인터페이스 결정 그대로다.

### 정보성 발견 Mem4 — 같은 파일에 연결 2개

리뷰가 기록해 둔 사실: episodic과 long-term이 **같은 `orchestrator.db` 공책을 각자 따로 펼친다**(`sqlite3.connect`를 각각 호출 — 연결 공유 없음, WAL 모드 미설정). **WAL**(Write-Ahead Logging)이란 SQLite의 운영 방식 옵션으로, "본문에 바로 쓰는 대신 별지에 먼저 적어 두는" 방식 — 여럿이 읽고 쓸 때 충돌을 줄여 준다. 지금은 펼치는 주체가 오케스트레이터 한 프로그램뿐이라 문제가 없고, 리뷰 결론도 "이번 범위에서는 현행 유지"였다. 나중에 동시 작업을 늘리게 되면 연결 하나를 공유하거나 `PRAGMA journal_mode=WAL`을 켜라는 메모만 남겼다 — 미래의 문제를 지금 코드로 풀지 않고 문서로 기록해 둔 사례.

---

## 4. 라이브 배선: 트리거가 실제로 당겨지는 곳

구현체(저장 장치)만 보면 "누가 언제 부르나"가 안 보이므로, 실제 연결 지점을 모아 둔다.

```python
# __main__.py — 오케스트레이터 조립
db_path = str(Path(wiring.memory_dir) / "orchestrator.db")  # episodic + long-term (A4)
...
longterm=SqliteLongTermMemory(db_path),
episodic=SqliteEpisodicMemory(db_path),
```

```python
# orchestrator/app.py — 트리거 4개
seed = _episodic_seed(episodic.last_for(symbol)) ...        # ① 실행 시작: episodic 읽기
chosen = plan_dimensions(state["symbol"], registry, state["longterm"])  # ② 플래너: long-term 읽기
episodic.put(RunRecord(...))                                 # ③ 실행 종료: episodic 쓰기
longterm.add_facts(symbol, report.key_points)                # ④ 실행 종료: long-term 쓰기
```

- 첫 코드는 "프로그램 시작 시 일기장과 수첩을 같은 공책 파일로 연다"는 뜻, 둘째 코드는 "분석 한 번의 시작과 끝에서 네 번 기억을 만진다"는 뜻이다: ① 시작할 때 지난 분석 읽기 → ② 계획 짤 때 수첩 읽기 → ③ 끝나면 일기 쓰기 → ④ 끝나면 수첩에 사실 추가.
- ④에서 장기 기억에 쌓이는 "사실"의 정체가 드러난다: **합성 보고서의 key_points(핵심 요점)** 다. 별도의 "사실 추출" 단계를 만들지 않고, 이미 잘 추려진 산출물을 재활용한다. 그래서 add_facts의 dedup이 중요하다 — 같은 코인을 반복 분석하면 비슷한 핵심 요점이 반복해서 들어오므로.
- working 층(연습장)의 트리거는 오케스트레이터가 아니라 **워커의 작업 그래프 내부**에 있다(§1 참조): `data` 노드가 적음 → checkpointer가 파일로 저장 → `work` 노드가 읽음.

검증은 결정 T7b대로 전부 **스텁 기반 결정적 테스트**다 — 진짜 AI(LLM)를 부르지 않고 가짜 응답으로 돌려서, 실행할 때마다 결과가 똑같게 만든 테스트: `test_episodic_roundtrip`(두 번째 실행이 첫 실행을 참조하는지), `test_longterm_affects_plan`(수첩 내용이 계획을 바꾸는지), `test_db_topology`(A4 공책 배치가 맞는지), `test_longterm_memory`(O2 중복 제거가 되는지).

---

## 5. 관통하는 설계 원칙 요약

1. **공책을 나누는 단위는 기억의 층이 아니라 쓰는 사람(writer)이다 (A4)** — episodic과 long-term은 층이 다르지만 쓰는 사람(오케스트레이터)이 같아 한 파일에 동거하고, working은 층이 하나지만 쓰는 사람(워커)이 4명이라 파일이 4개다. SQLite의 "여럿이 동시에 쓰면 충돌" 문제를 코드 기교가 아닌 **자리 배치(topology)** 로 제거했다.
2. **트리거 없는 메모리는 장식이다 (DESIGN 전제 5)** — 세 층 모두 "누가 언제 읽고 쓰는가"가 코드 설명문과 실제 가동 코드(`app.py`, `serve_worker.py`)에 박혀 있다. 저장소를 만들어 놓고 아무도 안 쓰는 층이 없다(W2 수정으로 working까지 실제 연결 완료).
3. **이미 있는 장치를 다시 발명하지 않는다 (C2)** — 연습장을 위한 별도 저장소를 새로 짓는 대신, LangGraph의 상태 + checkpointer가 이미 그 역할임을 인정했다. 쓰이지 않게 된 약속(Protocol)은 지우는 대신 설명문으로 사연을 기록했다.
4. **경계 안쪽은 최소 도구로** — 프로그램 사이의 경계(MCP/A2A)는 진짜 통신이 오가야 하지만 메모리는 아니다. 그래서 별도 서비스가 아닌 라이브러리, 큰 번역기(ORM)가 아닌 기본 `sqlite3`, 전용 설치 도구가 아닌 `CREATE TABLE IF NOT EXISTS`.
5. **내가 저장한 것도 검증해서 꺼낸다** — `model_dump_json`으로 넣고 `model_validate_json`으로 꺼낸다. DB를 거쳤다고 양식 검사를 면제하지 않는다. 모든 질의는 `?` 빈칸 끼워넣기(파라미터 바인딩)로 — 입력이 명령으로 둔갑하지 못하게.
6. **"항상 같은 결과"는 공짜가 아니다** — 같은 초에 끝난 실행을 가르는 `ORDER BY ts DESC, rowid DESC`의 2차 기준, add_facts의 "수첩 대비 + 이번 묶음 안" 이중 중복 제거. "거의 항상 맞는" 코드와 "항상 맞는" 코드의 차이는 이런 한 줄들이고, 각각을 겨누는 테스트가 있다.
7. **리뷰에서 발견된 문제는 코드 또는 기록으로 닫는다** — O2(무제한 적재)는 중복 제거 코드 + 테스트로, Mem4(연결 2개·WAL 미설정)는 "지금은 유지 + 확장 시 고려" 문서 기록으로. 모든 발견을 다 고치는 게 아니라, **"지금 고칠 범위인가"라는 판단 자체가 결정에 포함**된다.
