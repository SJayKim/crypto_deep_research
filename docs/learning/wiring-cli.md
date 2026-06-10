# 학습 자료: 배선(wiring) · CLI · 서비스 기동 완전 해부

> 대상: `crypto_deep_research/wiring.py`, `crypto_deep_research/__main__.py`, `crypto_deep_research/serve_worker.py`.
> 목적: 각 코드가 **무슨 의미**인지, **무슨 기능**인지, **왜 이렇게 설계했는지**를 한 줄 단위로, 개발을 모르는 사람도 따라올 수 있게 풀어 이해하기.
> 설계 결정 코드(A3, A4, M0 AC#5, M5 AC#2, WC1~WC3)의 원 출처는 [docs/DESIGN.md](../DESIGN.md)의 결정 테이블과 [docs/reviews/06-wiring-cli-packaging.md](../reviews/06-wiring-cli-packaging.md). (결정 코드란 "이 설계는 왜 이렇게 했는가"를 문서에 번호 붙여 적어둔 것 — 회의록의 안건 번호 같은 것이다.)

---

## 0. 큰 그림: 이 세 파일은 "시스템의 바깥 껍데기"다

이 시스템은 여러 개의 작은 프로그램(프로세스)이 협력해서 코인을 분석한다. contracts가 "프로그램끼리 주고받는 편지의 양식"이라면, 여기서 다루는 세 파일은 **그 프로그램들을 실제 세상에 꽂아 넣는 콘센트 자리**다:

```
.env / 환경변수
   │
   ├─▶ wiring.py        "서비스들이 서로 어디에 있는가" (URL·타임아웃·메모리 경로)
   │
   ├─▶ __main__.py      사용자 진입점: python -m crypto_deep_research "analyze BTC now"
   │                      → 오케스트레이터 1회 실행 → 보고서 출력 → exit code
   │
   └─▶ serve_worker.py  워커 진입점: python -m crypto_deep_research.serve_worker
                          → WORKER_KIND env로 4종 중 하나를 골라 HTTP 서버로 기동
```

먼저 용어 몇 개를 비유로:
- **env 변수(환경변수)** = 프로그램을 켜기 전에 책상 위에 적어두는 설정 메모. "워커 주소는 여기, 30초 넘으면 포기" 같은 내용을 메모(`.env` 파일)에 적어두면, 프로그램이 켜질 때 그 메모를 읽는다.
- **CLI** = 마우스 클릭 대신 글자 명령으로 프로그램을 부리는 방식. 검은 창에 `python -m crypto_deep_research "analyze BTC now"`라고 타이핑하는 것.
- **진입점** = 건물의 정문. 코드가 아무리 많아도 프로그램이 시작되는 문은 정해져 있고, 이 시스템엔 정문이 두 개다(사용자용 `__main__.py`, 워커용 `serve_worker.py`).
- **오케스트레이터 / 워커** = 오케스트라 지휘자와 연주자. 지휘자(오케스트레이터)가 "BTC 분석해" 지시를 4명의 연주자(시세·호가·여론·온체인 워커)에게 나눠주고 결과를 모아 보고서를 만든다.
- **exit code** = 프로그램이 끝나면서 운영체제에 남기는 한 자리 성적표. 0이면 "잘 끝났음", 0이 아니면 "문제 있었음".

세 파일의 공통 철학: **에이전트 코드(orchestrator/, workers/)는 "자기가 어디에 배포되는지"를 모른다.** 주소(URL), 포트, DB 경로 같은 배치 정보는 전부 환경변수 메모로 들어오고, 이 세 파일이 그 메모를 읽어 에이전트 코드에 건네준다. "설정은 코드가 아니라 환경에 적는다"는 12-factor app 원칙(웹 서비스 업계의 유명한 운영 수칙집) 그대로다. 덕분에 같은 코드가 내 컴퓨터의 일반 프로그램으로도(M1~M4 단계), docker-compose 컨테이너(프로그램을 짐 꾸린 그대로 어디서나 똑같이 돌리는 포장 상자, 그리고 그 상자 여러 개를 한 번에 띄우는 도구)로도(M5 단계) 한 글자 수정 없이 돈다 — DESIGN.md의 배포 계획("During M1-M4 run as plain local processes. At M5, docker-compose brings up ... as packaging") 그대로.

참고: 여섯 번째 프로세스인 MCP 서버(외부 데이터를 떠다 주는 "자료실 창구" 프로그램)의 진입점 `crypto_deep_research/mcp_server/__main__.py`는 별도의 mcp-server 학습 문서에서 다룬다.

---

## 1. `wiring.py` — 환경변수에서 읽는 정적 서비스 배선

### 배경: 왜 "배선"이라는 모듈이 따로 있나

배선(wiring)이란 말 그대로 전기 배선처럼 "누가 누구에게 어떤 선으로 연결되는가"다. 이 시스템은 6개 프로세스(오케스트레이터 + 워커 4 + MCP 서버)이고, 지휘자는 연주자들의 주소를 알아야 한다. **M0 단계에서 못 박은 결정**이 "wiring: static service URLs via env vars (one per worker + the MCP server)" (DESIGN.md M0 항목) — 즉 주소록을 환경변수 메모에 고정으로 적어두는 방식이다. 워커가 스스로 명함(Agent Card)을 내밀면 자동으로 찾아내는 동적 발견 같은 기능은 v1 범위 밖이고, 주소 목록 메모면 충분하다.

또 하나의 결정: **worker registry(워커 명단)는 data-driven** — "Keep the worker registry data-driven (env-var list of worker URLs) so adding a worker never edits `orchestrator/`" (DESIGN.md). 풀어 말하면: 워커 명단을 코드 속 분기문이 아니라 "목록 데이터"로 두어서, 5번째 워커를 추가할 때 코드 수정이 아니라 `WORKER_URLS` 메모에 주소 한 줄 덧붙이는 것으로 끝나게 한다. 이건 워커 4개를 병렬 작업 공간(worktree)에서 동시에 개발한 방식과도 맞물린다 — 각 작업 차선이 orchestrator/ 코드를 안 건드려야 서로 충돌이 없다.

### 줄별 해설

```python
"""Static service wiring read from the environment.

Service URLs are required (no silent default); WORKER_TIMEOUT_S defaults to 30 (A3).
...
"""
```
- 이 코드는 "이 모듈의 두 가지 정책"을 파일 첫머리 설명문(docstring)으로 선언한다는 뜻이다: (1) 주소(URL)는 **반드시 적어야 하며, 안 적었을 때 몰래 쓰는 기본값이 없다**, (2) 타임아웃(상대를 기다려주는 제한 시간)만 기본값 30초가 있다 — **결정 A3**("Per-worker 30s timeout (env-configurable)" = 워커 하나당 30초 기다리고, 환경변수로 조절 가능)의 환경변수 쪽 절반.
- 왜 URL엔 기본값이 없나? `http://127.0.0.1:8101` 같은 기본 주소를 깔아두면, 메모 작성을 깜빡한 채 실행했을 때 "엉뚱한 주소로 전화를 걸고 → 아무도 안 받아서 시간 초과"라는 **헷갈리는 증상**으로 나타난다. 그보다는 켜자마자 "주소 메모가 없습니다"라고 또렷하게 알려주는 게 낫다. 이건 M0 AC#5("필수 env 누락 시 명확 에러")라는 합격 조건(acceptance)으로 명문화돼 있다.

```python
DEFAULT_WORKER_TIMEOUT_S = 30
DEFAULT_MEMORY_DIR = ".memory"
```
- 이 코드는 "기본 타임아웃 30초, 기본 메모리 폴더 `.memory`"라는 두 숫자/이름에 이름표를 붙여둔 것이다. 코드 곳곳에 맨 숫자 30을 흩뿌리는 대신 이름 있는 상수 하나로 모은다. 특히 `DEFAULT_MEMORY_DIR`는 serve_worker.py도 가져다 쓴다 — 두 파일이 서로 다른 기본 폴더를 쓰는 사고를, 같은 이름표를 공유하게 해서 원천 차단.

```python
class Wiring(BaseModel):
    worker_urls: list[str]
    mcp_url: str
    worker_timeout_s: int
    memory_dir: str
```
- 이 코드는 "읽어들인 배선 정보를 담는, 칸이 정해진 서류 양식"이라는 뜻이다. 워커 주소 목록, MCP 주소, 타임아웃, 메모리 폴더 — 딱 네 칸. CLAUDE.md 규약("untyped dict 금지" = 칸이 정해지지 않은 자유 메모지 금지)대로, `os.environ`이라는 "아무 글자나 적힌 메모 더미"를 **여기서 한 번 정식 서류로 옮겨 적으면**, 이후 코드는 전부 칸과 타입이 보장된 세계에서 논다. 환경변수를 읽는 행위가 코드 곳곳에 흩어지지 않고 이 모듈 한 곳에 모이는 것도 같은 효과.

```python
def _require(var: str) -> str:
    value = os.environ.get(var)
    if not value:
        raise RuntimeError(f"required env var {var} is unset; set it in .env (see .env.example)")
    return value
```
- 이 코드는 "필수 메모 항목을 확인하고, 없으면 그 자리에서 멈추고 알려준다"는 뜻이다. `not value` 조건은 **메모가 아예 없는 경우와 항목 이름만 있고 내용이 빈 경우(`WORKER_URLS=`)를 똑같이 취급**한다 — 둘 다 "주소를 안 적은" 같은 사고이므로.
- 에러 메시지가 **고치는 방법까지** 알려준다("set it in .env (see .env.example)" = ".env 파일에 적으세요, 예시는 .env.example 참고"). 이 프로젝트를 처음 받아본 사람이 에러 화면만 보고도 스스로 고칠 수 있게.

```python
def load_wiring() -> Wiring:
    worker_urls = [u.strip() for u in _require("WORKER_URLS").split(",") if u.strip()]
    if not worker_urls:
        raise RuntimeError("WORKER_URLS is set but contains no URLs")
```
- 첫 줄은 "콤마로 이어 적은 주소 목록을 쪼개고, 양옆 공백을 다듬고, 빈 조각은 버린다"는 뜻이다. `"url1, url2,"`처럼 띄어쓰기나 끝 콤마가 섞인, 사람 손으로 적은 메모를 관대하게 받아준다.
- 둘째 줄은 추가 검문이다: `WORKER_URLS=","` 같은 값은 첫 검문(`_require`)은 통과하지만(콤마 한 글자라도 적혀는 있으므로) 다듬고 나면 목록이 텅 빈다. 그 경우를 별도 메시지("적긴 적었는데 주소가 하나도 없습니다")로 잡는다 — "메모를 안 함"과 "메모는 했는데 내용이 없음"은 다른 실수라서 안내문도 다르게 했다. (리뷰 ② 체크리스트에서 정확성 항목으로 확인된 부분)

```python
    timeout_raw = os.environ.get("WORKER_TIMEOUT_S")
    return Wiring(
        worker_urls=worker_urls,
        mcp_url=_require("MCP_URL"),
        worker_timeout_s=int(timeout_raw) if timeout_raw else DEFAULT_WORKER_TIMEOUT_S,
        memory_dir=os.environ.get("MEMORY_DIR") or DEFAULT_MEMORY_DIR,
    )
```
- 이 코드는 "필수 항목과 선택 항목을 구분해 서류를 채운다"는 뜻이다. 그 비대칭이 코드에 그대로 보인다: `MCP_URL`은 `_require`(없으면 즉시 정지), `WORKER_TIMEOUT_S`와 `MEMORY_DIR`는 안 적었으면 기본값(30초, `.memory`)으로. 구분 기준: **"없으면 동작 자체가 달라지는 것(주소)"은 필수, "없어도 누구나 수긍할 기본이 있는 것(제한 시간, 저장 폴더)"은 선택** — 이 구분이 배선 설계의 한 축이다.
- `int(timeout_raw)`: 타임아웃 칸에 숫자가 아닌 글자를 적으면 프로그램이 `ValueError`로 죽는다. 잘못 적은 설정을 슬쩍 눈감아주는 방어 코드를 일부러 안 넣었다 — 일어나지 않을/잘못된 설정 시나리오용 에러처리 금지(Simplicity First 원칙). 설정이 틀렸으면 조용히 넘어가는 것보다 시끄럽게 죽는 게 맞다.

> 테스트: 리뷰 지적 사항 **WC1**("M0 AC#5는 명시적 합격 조건인데 `load_wiring` 전용 테스트가 없다")에 따라 `tests/test_wiring.py`가 추가됐다 — 메모 누락 시 `RuntimeError`가 나는지, 빈 `WORKER_URLS`에 에러가 나는지, 기본 타임아웃이 30인지를 자동으로 확인한다.

---

## 2. `__main__.py` — CLI 진입점: 질의 → 보고서 → exit code

### 배경

DESIGN.md의 성공 기준 1번이 이 파일의 존재 이유다: "`analyze BTC now` ... returns a synthesis report"(= "BTC 지금 분석해"라고 치면 종합 보고서가 나온다). 들어오는 방식도 결정돼 있다: "Entry via CLI: `python -m crypto_deep_research \"analyze BTC now\"`". 파이썬에는 "패키지 폴더 안에 `__main__.py`라는 파일을 두면 패키지 이름만으로 실행할 수 있다"는 관례가 있는데 그걸 쓴 것 — 별도의 실행 명령어 등록 절차 없이, 패키지만 설치돼 있으면 바로 실행된다.

이 파일은 의도적으로 **얇다**. 하는 일은 딱 4가지: 질문에서 코인 심볼(BTC 같은 종목 약칭) 뽑기, 배선 메모 읽기 + 메모리 준비, 오케스트레이터 1회 호출, 결과를 화면용 글로 바꾸기 + 성적표(exit code) 반환. 실제 분석 로직은 전부 `orchestrator/` 안에 있다. 정문은 안내만 하고, 일은 건물 안에서 한다.

### 줄별 해설

```python
_IGNORE = {"analyze", "now", "please", "the", "for", "me"}

def parse_symbol(query: str) -> str:
    for token in query.replace(",", " ").split():
        if token.isalpha() and token.lower() not in _IGNORE:
            return token.upper()
    raise ValueError(f"no symbol found in query: {query!r}")
```
- 이 코드는 "자연어 질문에서 코인 심볼만 골라내는 초미니 골라내기"라는 뜻이다. "analyze BTC now"를 단어로 쪼개고 → 무시할 단어 목록(`_IGNORE`, "analyze"·"now"·"please" 같은 군말)을 건너뛰고 → 처음 만나는 알파벳 단어를 대문자로 바꿔 `"BTC"`로 돌려준다.
- **왜 AI나 제대로 된 문장 분석기가 아니라 군말 목록 하나인가?**: 이번 단계의 완료 기준(DoD)이 `analyze BTC now` 한 문장이다. 이 입력을 처리하는 최소 코드가 이것이고, 그 이상은 요청하지 않은 기능이다.
- **알려진 한계 — 리뷰 지적 WC2**: "`parse_symbol`이 첫 알파벳 단어(무시 목록 제외)를 반환 → `analyze bitcoin now`→`BITCOIN`(이름→심볼 변환표 없음) → 조용한 빈틈. 이번 슬라이스는 `analyze BTC now`가 완료 기준이라 현행 허용" — 즉 "bitcoin"이라는 풀네임을 "BTC"로 바꿔주지 못하고, MCP 서버의 샘플 데이터(fixture)·CoinGecko 변환표가 **BTC/ETH만 지원**한다. 리뷰 결론은 "코드 고치기는 범위 밖, 대신 한계를 문서에 남긴다"였다. 지금 읽는 이 문서도 그 기록의 일부다.
- 심볼을 못 찾으면 `ValueError`로 멈춘다 — 빈 결과나 임의의 기본 심볼로 슬그머니 진행하지 않는다(조용한 실패 금지 원칙의 CLI 버전).

```python
def render_report(report: SynthesisReport) -> str:
    lines = [f"{report.headline}  [{report.status}]"]
    lines += [f"  - {point}" for point in report.key_points]
    if report.dimensions_unavailable:
        lines.append("Unavailable:")
        lines += [f"  ! {gap.dimension}: {gap.reason}" for gap in report.dimensions_unavailable]
    return "\n".join(lines)
```
- 이 코드는 "보고서 데이터를 사람이 읽는 글로 바꾼다"는 뜻이다. 첫 줄에 헤드라인과 상태 표시 `[{status}]`를 **반드시** 붙인다 — 일부만 성공했으면 `[partial]`이 제목 옆에 바로 보인다.
- `Unavailable:` 블록(분석에 실패한 차원과 그 이유를 나열)이 **결정 TENSION-C의 CLI 쪽 구현**이다: "The synthesis report carries explicit per-dimension coverage; **the CLI surfaces it**; a test asserts a 1-of-4 run is visibly marked partial"(= 보고서는 차원별 성공/실패를 명시하고, CLI가 그걸 화면에 드러내며, 4개 중 1개만 성공한 실행이 눈에 띄게 partial 표시되는지 테스트로 확인). contracts의 `dimensions_unavailable` 필드(양식 칸)가 여기서 화면 표시로 완성된다. 양식에 실패를 적어도 화면이 안 보여주면 사용자 입장에선 여전히 조용한 실패다.
- 이 함수는 화면 출력 없이 글자만 돌려주는 "순수 함수"다(재료를 넣으면 결과만 나오는 함수, 부엌 밖에 흔적을 안 남김). 덕분에 화면 출력을 가로채는 장치 없이도 테스트된다 — 리뷰 ④: "`render_report`/`exit_code`는 `test_partial`/`test_zero_artifact`에서 간접 검증".

```python
def exit_code(report: SynthesisReport) -> int:
    return 1 if report.status == "failed" else 0
```
- 이 코드는 "성적표 점수를 정하는 규칙"이다 — **결정 A3**의 마지막 조각: "zero-artifact path → `status=failed` report ..., **CLI exits non-zero**"(= 결과물이 하나도 없으면 실패 보고서를 내고 CLI는 0이 아닌 성적표를 남긴다). 4개 차원이 전부 실패해야 1이고, 일부 성공(partial)은 0이다 — 부분 성공은 (화면에 표시는 하되) 실패로 취급하지 않는다. 한 줄짜리인데 굳이 함수로 뽑은 이유: 이 규칙 자체가 합격 조건의 대상이라, 이름이 붙고 테스트가 달리는 독립 단위여야 하기 때문.

```python
async def _run(query: str) -> SynthesisReport:
    wiring = load_wiring()
    Path(wiring.memory_dir).mkdir(parents=True, exist_ok=True)
    db_path = str(Path(wiring.memory_dir) / "orchestrator.db")  # episodic + long-term (A4)
    return await run_orchestrator(
        symbol=parse_symbol(query),
        run_id="cli",
        worker_urls=wiring.worker_urls,
        longterm=SqliteLongTermMemory(db_path),
        timeout_s=float(wiring.worker_timeout_s),
        episodic=SqliteEpisodicMemory(db_path),
    )
```
- 여기가 **조립(composition root)** 이다 — 가구 공장에 비유하면, 부품(구체 구현)을 실제로 꺼내 조립하는 유일한 작업대. 환경변수 메모에서 배선을 읽고, 실제 부품(`SqliteEpisodicMemory`, `SqliteLongTermMemory` — SQLite라는 파일 한 개짜리 미니 데이터베이스를 쓰는 메모리 구현)을 만들어 오케스트레이터에 **건네준다(주입)**. `run_orchestrator`는 "메모리라면 이런 동작을 할 수 있어야 한다"는 규격(Protocol `LongTermMemory`/`EpisodicMemory`)만 알 뿐, 부품이 SQLite제인지는 모른다 — 그래서 테스트에선 가짜 부품을 꽂을 수 있다. 실제 부품 상표를 아는 곳은 정문(진입점)뿐이라는, 의존성 주입의 교과서적 배치.
- `mkdir(parents=True, exist_ok=True)`: 첫 실행 시 `.memory/` 폴더가 없으면 알아서 만들고, 이미 있으면 그냥 넘어간다(exist_ok). 몇 번을 다시 실행해도 안전(멱등 = 여러 번 해도 한 번 한 것과 같음).
- **결정 A4**가 주석에 박혀 있다: "orchestrator solely owns episodic + long-term DB (single-writer-per-file)"(= 일지 메모리와 장기 메모리 DB는 오케스트레이터만 소유, 파일 하나에 쓰는 사람은 하나). 일지(episodic)와 장기(long-term) 두 메모리가 **같은 파일** `orchestrator.db`를 써도 되는 이유 — A4의 규칙은 "공책 한 권에 펜을 쥐는 사람은 한 명"인데, 두 메모리의 펜잡이가 둘 다 오케스트레이터(같은 프로세스)다. 반면 워커들의 체크포인터 DB(작업 중간 저장 공책)는 각자 별도 파일이다(§3 참조).
- `run_id="cli"`: CLI는 한 번에 한 건만 실행하므로 실행 번호표는 고정 글자 "cli"면 충분. 고유 번호 생성기는 필요해지는 날 만든다.

```python
def main(argv: list[str]) -> int:
    if not argv:
        print('usage: python -m crypto_deep_research "analyze BTC now"', file=sys.stderr)
        return 2
    report = asyncio.run(_run(" ".join(argv)))
    print(render_report(report))
    return exit_code(report)

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```
- 성적표(exit code) 어휘가 셋으로 갈린다: **2 = 사용법 오류**(질문을 아예 안 줌 — "사용법 잘못은 2"라는 Unix 세계의 오랜 관례), **1 = 분석 전체 실패**(A3), **0 = 성공 또는 부분 성공**. 사용법 안내는 stderr(오류 전용 출구)로 내보낸다 — stdout(정상 출력 전용 출구)은 보고서만 나가는 통로라, 출력 결과를 다른 프로그램에 이어 붙여도(파이프) 안내문이 섞여 들어가지 않는다.
- `" ".join(argv)`: 따옴표 없이 `python -m crypto_deep_research analyze BTC now`로 쳐서 셸(명령 해석기)이 세 단어로 쪼개 넘겨도, 다시 한 문장으로 합쳐서 처리한다. 사용자 실수에 관대.
- `main(argv) -> int`를 `sys.argv`/`sys.exit`(실제 운영체제와 닿는 부분)에서 분리: 테스트는 단어 목록을 넣고 숫자만 받으면 끝 — 프로그램을 진짜로 띄울 필요가 없다.
- `asyncio.run`: 오케스트레이터 내부는 비동기(async — 여러 일을 기다리는 동안 다른 일을 하는 방식. 워커 4개에 동시에 일을 시켜야 하므로)지만, CLI 자체는 한 줄씩 순서대로 도는 동기 세계다. 그 경계에서 딱 한 번 비동기 엔진(이벤트 루프)을 돌린다.

---

## 3. `serve_worker.py` — 워커 1개의 프로세스 진입점

### 배경: 왜 이 파일이 `workers/` 밖에 있는가 (M5 AC#2)

파일 첫머리 설명문이 답을 직접 말한다: "Lives outside `workers/` on purpose: it's **packaging, not agent code**, so the M5 live swap leaves `workers/` and `orchestrator/` **byte-for-byte unchanged** (AC#2)" — "일부러 `workers/` 밖에 둔다. 이건 분석 코드가 아니라 포장(packaging)이라서, M5의 실데이터 전환 작업 후에도 `workers/`와 `orchestrator/`는 1바이트도 안 바뀐다."

M5의 합격 조건(AC#2)은 "샘플 데이터 → 실제 데이터 소스로 갈아끼우고 도커 포장까지 해도 에이전트 코드는 1바이트도 안 바뀐다"였다. 정문·포트·환경변수 같은 배치 관심사가 `workers/` 폴더 안에 섞여 있으면, 포장 작업을 할 때마다 에이전트 코드에 수정 흔적(diff)이 남는다. 그래서 "어떻게 분석하는가"(workers/)와 "어떻게 켜져 있는가"(이 파일)를 폴더 수준에서 갈랐다. 내용물과 포장지를 다른 서랍에 두는 것이다. 리뷰도 이를 확인했다: "M5 AC#2: `serve_worker.py`가 `workers/` 밖 packaging 계층 — live swap이 agent 코드 무변경".

또 하나의 포인트: **워커 4종이 실행 파일 하나를 공유한다.** 설명문의 "a worker container is just an image + env" — 도커 이미지(포장 상자의 설계도)는 1개고, 상자를 열 때 붙이는 메모 `WORKER_KIND=market`이냐 `sentiment`냐에 따라 4개 컨테이너가 서로 다른 워커가 된다. 같은 설계도 4부에 라벨만 다르게 붙이는 셈 — 설계도 4개를 따로 만들어 관리하는 것보다 훨씬 싸다.

### 줄별 해설

```python
_BUILDERS: dict[str, Callable[[str, str, Any], Starlette]] = {
    "market": build_market_app,
    "orderbook": build_orderbook_app,
    "sentiment": build_sentiment_app,
    "onchain": build_onchain_app,
}
```
- 이 코드는 "`WORKER_KIND` 이름 → 그 워커 앱을 만들어주는 공장 함수"의 명부(registry)다. "이름이 market이면 이렇게, orderbook이면 저렇게..." 하는 if/elif 갈림길 대신 명부(dict, 이름표→값 대응표)를 쓴 이유: 설명문의 "Adding a worker = **one registry entry here** + a compose service" — 워커 추가가 갈림길 로직 수정이 아니라 명부에 한 줄 적기가 되게 한다. wiring.py의 `WORKER_URLS`(지휘자 쪽 주소록)와 짝을 이루는, 워커 쪽 명부다.
- 명부에 오른 공장 함수 4개는 모두 받는 재료가 똑같다(`(mcp_url, public_url, checkpointer) -> Starlette`). 4개 워커 서비스가 같은 모양의 공장을 내놓기로 한 암묵적 약속 — 그래야 이 명부 방식이 성립한다.

```python
def build_app(checkpointer: Any = None) -> Starlette:
    builder = _BUILDERS[os.environ["WORKER_KIND"]]
    return builder(os.environ["MCP_URL"], os.environ["PUBLIC_URL"], checkpointer)
```
- 환경변수 메모 3장의 역할: `WORKER_KIND` = "나는 어떤 워커인가", `MCP_URL` = "자료실(MCP 서버)은 어디인가", `PUBLIC_URL` = 내 명함(Agent Card)에 적을 **남에게 알려주는 내 주소**. 알려주는 주소와 실제로 문을 여는 주소(bind 주소)는 다를 수 있다 — 컨테이너 안에서는 `0.0.0.0`(모든 문)에 귀를 열지만, 명함에는 `http://market-worker:8101`처럼 밖에서 찾아올 수 있는 주소를 적어야 한다. 회사 안에선 "3번 회의실"이지만 명함엔 도로명 주소를 적는 것과 같다.
- `os.environ["..."]` 직접 꺼내기: 메모가 없으면 그냥 `KeyError`(열쇠 없음 에러)로 죽는다. wiring.py의 친절한 `_require`와 결이 다른데, 리뷰는 이를 인지하고 수용했다(② "[△] 누락 시 명확한 메시지 없이 KeyError(엔트리라 허용 범위)") — compose(상자 일괄 기동 도구)가 메모를 항상 채워주는 배치 전제에서, 정문 한 곳의 KeyError에 친절한 안내문까지 다는 건 과잉이라는 판단.
- `build_app`을 `__main__` 블록(실행 시에만 도는 구역) 밖의 일반 함수로 뽑은 이유: 테스트(그리고 서버를 진짜 안 띄우고 프로세스 안에서 직접 검사하는 in-process ASGI 기반 E2E — 결정 T8)가 서버 기동 없이 앱 객체만 받아 검증할 수 있게.

```python
if __name__ == "__main__":
    dimension = cast(Dimension, os.environ["WORKER_KIND"])
    memory_dir = os.environ.get("MEMORY_DIR") or DEFAULT_MEMORY_DIR
    Path(memory_dir).mkdir(parents=True, exist_ok=True)
    with worker_checkpointer(working_db_path(memory_dir, dimension)) as cp:
        uvicorn.run(build_app(cp), host="0.0.0.0", port=int(os.environ["PORT"]))
```
- `cast(Dimension, ...)`: 환경변수 글자를 "분석 차원 이름(Dimension)"으로 간주하겠다는 타입 표시일 뿐, 실제 검사는 아니다. 틀린 값이면 어차피 바로 다음 줄의 명부 조회 `_BUILDERS[...]`에서 KeyError로 죽으므로, 같은 검사를 두 번 달지 않았다.
- `working_db_path(memory_dir, dimension)` → `.memory/working-market.db` 식으로 **워커마다 자기 공책 파일**을 받는다. **결정 A4** "Each worker owns its own checkpointer DB ... (single-writer-per-file)"의 구현 — 워커 4명이 SQLite 공책 한 권을 동시에 쓰려 들면 펜 뺏기 싸움(잠금 경합)이 나므로, 공책을 쪼개 한 권당 펜잡이를 1명으로 고정한다. 오케스트레이터의 `orchestrator.db`(§2)와 합쳐 보면 "DB 파일 1개 = 소유 프로세스 1개"라는 전체 지형이 완성된다(`tests/test_db_topology.py`가 자동 검증).
- `with worker_checkpointer(...) as cp:` — `with` 구문(들어갈 때 열고 나올 때 반드시 닫아주는 자동문, context manager)이 체크포인터의 수명을 책임진다(memory/working.py 설명문: "The caller owns the checkpointer's lifetime" = 호출한 쪽이 수명을 소유한다). 서버가 내려가면 DB 연결도 같이 정리된다.
- `host="0.0.0.0"`: 컨테이너 밖(compose 내부망의 오케스트레이터)에서 찾아오게 하려면 모든 문(네트워크 인터페이스)을 열어둬야 한다. 단, 리뷰 지적 **WC3**가 이 한 줄의 보안 의미를 기록해 뒀다: "A2A 워커·MCP가 **무인증**(신분 확인 없음)으로 `0.0.0.0` 노출 ... compose 내부망/내 컴퓨터 안에서만 쓴다는 전제로는 의도된 설계이나, 외부 네트워크에 노출되면 누구나 `analyze`를 호출 가능" — 인증 기능은 이번 에픽에서 명시적으로 범위 밖이고, "믿을 수 있는 내부망에서만 돌린다"가 운영 전제로 명문화됐다. 이 서버를 인터넷에 그대로 노출하면 안 된다.
- `port=int(os.environ["PORT"])`: 포트란 한 건물(컴퓨터)의 호실 번호다 — 주소가 같아도 호실이 다르면 다른 가게다. 같은 컴퓨터에 워커 4개를 띄우려면 호실이 달라야 하므로 포트 번호도 환경변수 메모로 받는다. 컨테이너 세계의 표준 관례이기도 하다.

### 두 진입점의 대칭 구조

| | `__main__.py` (오케스트레이터) | `serve_worker.py` (워커) |
|---|---|---|
| 수명 | one-shot: 실행하고 끝 | long-running: HTTP 서버 |
| 입력 | argv(자연어 질의) | env(`WORKER_KIND` 등) |
| 메모리(A4) | `orchestrator.db` (episodic+long-term) | `working-<kind>.db` (자기 checkpointer) |
| 상대 등록부 | `WORKER_URLS` (워커들이 어디 있나) | `_BUILDERS` (내가 어떤 워커인가) |
| compose에서 | profile `run`의 oneshot | 항상 떠 있는 서비스 4개 |

(읽는 법: 오케스트레이터는 "한 번 뛰고 퇴근하는 심부름꾼", 워커는 "항상 카운터를 지키는 가게"다. 각자 자기 공책을 따로 쓰고, 서로를 찾는 명부도 따로 둔다.)

---

## 4. 관통하는 설계 원칙 요약

1. **배치 정보는 env로, 코드는 배치를 모르게** — 주소·포트·타임아웃·DB 경로는 전부 환경변수 메모. 같은 에이전트 코드가 내 컴퓨터(M1~M4)에서도 docker-compose 상자(M5)에서도 무변경으로 돈다. 포장 계층(`serve_worker.py`)을 `workers/` 밖에 둔 것도 같은 원칙의 폴더 버전(M5 AC#2).
2. **등록부는 데이터, 분기는 금지** — 오케스트레이터 쪽 `WORKER_URLS`(콤마 목록), 워커 쪽 `_BUILDERS`(명부). 워커 추가 = 메모 한 줄 + 명부 한 줄 + compose 서비스 한 칸. orchestrator/ 코드 수정 0줄.
3. **필수는 시끄럽게, 선택은 기본값으로** — 주소는 `_require`로 즉시 또렷한 에러(M0 AC#5), 타임아웃·메모리 경로는 누구나 수긍할 기본값(30초, `.memory`). 몰래 깔린 기본 주소 같은 "친절해 보이는 함정"을 만들지 않는다.
4. **exit code도 계약이다 (A3·TENSION-C)** — 성적표 규칙: 0 = 성공/부분 성공, 1 = 전 차원 실패, 2 = 사용법 오류. 부분 성공은 성적표 0이되 `render_report`가 `[partial]` 표시와 `Unavailable:` 블록으로 반드시 화면에 드러낸다. 양식(contracts) → 화면(CLI) → 성적표(exit code)까지, 실패가 보이게 만드는 사슬이 끝까지 이어진다.
5. **진입점은 조립만, 로직은 안쪽에** — `_run`이 실제 SQLite 부품을 만들어 규격(Protocol) 인자로 꽂아주는 조립대(composition root). `parse_symbol`/`render_report`/`exit_code`/`build_app`을 순수 함수로 뽑아, 프로그램을 진짜 띄우지 않고도 테스트 가능.
6. **완료 기준까지만 만든다 — 한계는 기록한다 (WC2·WC3)** — `parse_symbol`은 사실상 BTC/ETH 심볼만 의미 있게 동작하고("bitcoin"→"BITCOIN"은 변환표 없음), 서버 문은 신분 확인 없이 열려 있다(믿을 수 있는 내부망 전제). 둘 다 리뷰에서 "지금 고치는 대신 문서로 남긴다"로 결정된, 의도적으로 좁힌 범위다.
