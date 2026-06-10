# 학습 자료: `mcp_server/` 패키지 완전 해부

> 대상: `crypto_deep_research/mcp_server/` 의 5개 모듈 (server.py, \_\_main\_\_.py, sources/base.py, sources/fixture.py, sources/coingecko.py).
> 목적: 각 코드가 **무슨 의미**인지, **무슨 기능**인지, **왜 이렇게 설계했는지**를 한 줄 단위로 이해하기.
> 설계 결정 코드(A3, A4, M5 AC#2/AC#4, S2, S3)의 원 출처는 [docs/DESIGN.md](../DESIGN.md)의 Locked Decisions 테이블과 [docs/reviews/02-mcp-server.md](../reviews/02-mcp-server.md).
> 도구의 입출력 스키마(`OHLCV`, `Orderbook`, `News`, `OnchainMetrics`)는 [contracts.md](./contracts.md) §6에서 이미 다뤘으므로 여기서는 참조만 한다.

---

## 0. 큰 그림: MCP 서버는 시스템에서 어디에 있나

```
오케스트레이터 ──A2A──▶ 워커 4개 ──MCP(streamable HTTP)──▶ 코인 데이터 MCP 서버
                                                              │
                                                              └─ DataSource (fixture | coingecko)
```

먼저 용어 하나. **MCP**는 "AI 에이전트가 외부 도구를 쓸 때 따르는 표준 규격"이다. 비유하면 **전기 콘센트 규격** 같은 것 — 어떤 가전(에이전트)이든 규격에 맞는 플러그만 있으면 어떤 콘센트(도구 서버)에든 꽂아 쓸 수 있다. 이 MCP 서버는 우리 시스템을 이루는 6개 프로그램(프로세스) 중 하나로, **"에이전트→도구" 사이의 경계**, 즉 그 콘센트 역할을 맡는다. 일하는 직원(워커) 4명이 동시에 이 콘센트에 꽂아 각자 필요한 코인 데이터를 가져간다. 핵심 성격 두 가지:

1. **무상태(stateless) + 읽기 전용** — "무상태"란 서버가 **아무것도 기억하지 않는다**는 뜻이다. 비유하면 안내데스크 직원이 손님을 기억하지 않고, 누가 와서 뭘 물어도 매번 책(데이터 출처)을 펼쳐 그대로 읽어주는 것. 이것이 **설계 결정 A4**: "MCP server stateless." 모든 도구 호출은 source를 읽고 돌려줄 뿐, 여럿이 같이 만지는 변하는 데이터가 없다. 그래서 워커 4명이 동시에 물어봐도 줄 세우기(lock, 잠금) 없이 안전하고, 누가 언제 물어도 같은 답이 나온다 (`test_mcp_server::test_concurrent_calls_return_identical_data`가 검증).
2. **데이터 출처와 도구 표면의 분리** — 손님에게 보이는 **창구 4개(도구)의 모양은 고정**이고, 창구 뒤의 자료실(`DataSource`)만 갈아끼운다. M1 단계에서는 견본 데이터(fixture, 미리 만들어 둔 가짜 데이터 파일), M5 단계에서는 CoinGecko 실제(라이브) 데이터. **M5 AC#2**: "fixture→live 교체는 이 패키지 + env로만, 에이전트 코드 무변경." (env = 환경변수. 프로그램을 켤 때 바깥에서 꽂아주는 **설정 쪽지** 같은 것이다.)

**왜 공식 SDK(FastMCP)인가?** SDK란 "남이 미리 만들어 둔 부품 상자"다. A2A 통신은 직접 손으로 만들었는데(A1) MCP는 남이 만든 부품을 쓴 것이 모순처럼 보이지만, [TECH-CHOICES.md](../TECH-CHOICES.md) §⑥이 명시한 **의도된 비대칭**이다. 이유는 "무엇을 배우려 했는가"가 다르기 때문: A2A에서 배우려던 것은 통신 규약의 *속 구조*(직접 만들어야 배움), MCP에서 배우려는 것은 "에이전트와 도구 사이에 표준 경계를 둔다"는 *위치와 개념*(경계가 어디 있는지가 핵심이지, 이미 정해진 규격을 다시 만드는 건 배움이 아님). 한 줄 비유: "운전(A2A)은 직접 배우고, 도로(MCP)는 직접 깔지 않는다."

**왜 stdio가 아니라 streamable HTTP인가?** 둘 다 "서버와 대화하는 통로"의 종류다. stdio는 부모 프로그램이 자식 프로그램을 직접 띄워 둘이서만 속닥이는 **내선 전화** 방식(Claude Desktop 같은 데스크톱 앱용, 1:1 전용). 반면 HTTP는 인터넷에서 쓰는 보편적 통신 방식 — 누구나 전화번호(주소)만 알면 걸 수 있는 **대표 전화**다. 이 서버는 혼자 도는 **독립 프로그램/컨테이너**이고 워커 4명이 동시에 걸어와야 하므로, 여러 명을 받을 수 있는 HTTP가 맞다 (DESIGN.md: "Workers connect as MCP clients over streamable HTTP (not stdio: the server is its own process/container)").

파일 구조와 의존 방향:

```
__main__.py  (프로세스 엔트리 — env 읽어 조립)
   └─▶ server.py  (FastMCP 서버 팩토리 — 도구 4개 등록)
          └─▶ sources/base.py     (DataSource Protocol — 출처의 계약)
                 ├─ sources/fixture.py    (FixtureSource — JSON 견본)
                 └─ sources/coingecko.py  (CoinGeckoSource — 라이브 + 429 재시도)
```

---

## 1. `server.py` — FastMCP 서버 팩토리

### 줄별 해설

```python
from mcp.server.fastmcp import FastMCP
from crypto_deep_research.contracts.mcp_tools import OHLCV, News, OnchainMetrics, Orderbook
from crypto_deep_research.mcp_server.sources.base import DataSource
from crypto_deep_research.mcp_server.sources.fixture import FixtureSource
```
- 이 코드는 "필요한 부품들을 가져온다"는 뜻이다.
- `FastMCP`: 공식 `mcp` SDK(부품 상자)에 들어있는 완성형 서버 부품. 보통 함수에 표시(데코레이터) 하나만 붙이면 그 함수가 곧 MCP 도구가 된다.
- 돌려주는 데이터의 형식은 전부 `contracts/mcp_tools.py`의 Pydantic 모델 — 즉 MCP 경계를 넘는 데이터도 아무 형태나 담는 자루(untyped dict)가 아니라, 칸이 정해진 **공식 서식**(공유 계약, C5)에 담는다. 서식 자체의 의미는 [contracts.md §6](./contracts.md) 참조.

```python
def build_server(source: DataSource | None = None, host: str | None = None) -> FastMCP:
    src: DataSource = source or FixtureSource()
```
- 이 코드는 "서버를 즉석에서 만들지 않고, 주문을 받아 조립해 주는 **조립 공장(팩토리 함수)**을 둔다"는 뜻이다. 파일을 불러오는 순간 서버가 자동으로 생기는 게 아니라, 부르는 쪽이 데이터 출처(source)와 접속 주소(host)를 골라 넣어 조립한다. 덕분에 테스트에서는 `build_server(가짜_source)`로 실제 인터넷 호출 없이 서버를 띄울 수 있다 (CLAUDE.md 규약: 테스트에서 라이브 API 호출 금지).
- `source` 기본값이 `FixtureSource()`: 아무것도 안 넣으면 견본 데이터로 동작한다. `python -m ...server`로 그냥 띄워도 굴러가는 안전한 기본값.
- `src: DataSource` 타입 표기: 이 함수가 아는 것은 **"출처라면 이런 일을 할 수 있어야 한다"는 자격 요건(Protocol)뿐**이다. 뒤에 있는 게 견본인지 CoinGecko인지 모른 채 정해진 4개 기능만 부른다 — 출처를 갈아끼워도 이 파일을 안 고치는 이유.

```python
    # host set (e.g. 0.0.0.0 under compose) binds non-localhost and skips FastMCP's
    # localhost-only DNS-rebinding guard so in-cluster workers can reach it; None = default.
    mcp = FastMCP("coin-data", host=host) if host else FastMCP("coin-data")
```
- 이 코드는 "접속 주소(host)가 주어졌으면 그 주소로 문을 열고, 안 주어졌으면 기본대로 연다"는 뜻이다.
- `"coin-data"`: 이 MCP 서버의 이름(접속한 쪽이 보게 되는 간판).
- **host 분기가 왜 필요한가**: FastMCP는 기본적으로 "우리 집 안에서만 받는 문"(localhost, 같은 컴퓨터 내부 전용 주소)을 열고, DNS-rebinding이라는 해킹 수법(외부 사이트가 주소를 속여 내부 서버에 접근하는 수법)을 막는 잠금장치를 켠다. 그런데 docker-compose 환경(여러 프로그램을 각자의 방=컨테이너에 넣어 함께 돌리는 방식)에서는 워커들이 `mcp:8000` 같은 **집 밖 주소**로 찾아와야 하므로, `MCP_HOST=0.0.0.0`(아무 주소로나 받겠다는 표시)을 줘서 그 잠금장치를 풀어야 한다. 리뷰 02는 이를 "의도된 in-cluster(같은 울타리 안) 접근, 무인증은 이번 작업 범위(epic) 밖"으로 기록했다(정보성, WC3과 동일한 입장).
- `if host else` 분기인 이유: host가 없을 때 굳이 `host=None`을 건네지 않고 SDK의 기본 동작(localhost + 잠금장치)을 그대로 둔다 — **필요할 때만 기본에서 벗어난다**는 태도.

```python
    @mcp.tool()
    def get_ohlcv(symbol: str, interval: str = "1d") -> OHLCV:
        """Recent OHLCV bars for a symbol."""
        return src.get_ohlcv(symbol, interval)
```
- 이 코드는 "이 함수를 MCP 도구 하나로 등록한다"는 뜻이다. `@mcp.tool()`이라는 표시(데코레이터) 한 줄이면, SDK가 함수의 모양(입력·출력 형식)과 설명문(docstring)을 읽어 "이런 도구가 있어요"라는 안내문을 **자동으로 만들어** 접속자(워커)에게 보여준다. 직접 만들었으면 수십 줄일 일이 한 줄로 끝난다.
- 본문이 `return src.get_ohlcv(...)` 한 줄: 서버는 **얇은 중계자(어댑터)**다. 실제 일은 출처(source)가 하고, 서버는 MCP 규격으로 포장해 내놓기만 한다. 도구 호출마다 출처를 읽고 끝 — 이게 A4 "무상태"의 실체다(서버 안에 임시 저장소도, 호출 횟수표도, 손님별 기록도 없다).
- `get_orderbook` / `get_news` / `get_onchain`도 같은 패턴으로, 도구 4개가 등록된다. 워커별 대응: market→get_ohlcv, orderbook→get_orderbook, sentiment→get_news, onchain→get_onchain.

```python
if __name__ == "__main__":
    build_server().run(transport="streamable-http")
```
- 이 코드는 "이 파일을 직접 실행하면 견본 데이터 기본값으로 서버를 켠다"는 뜻 — 개발할 때 쓰는 지름길이다. `transport="streamable-http"`가 위에서 설명한 "대표 전화(HTTP)" 방식을 고르는 부분이다 (주소는 127.0.0.1:8000/mcp).
- 정식 출입구는 `__main__.py` 쪽 — 아래 참조.

---

## 2. `__main__.py` — env 기반 프로세스 엔트리

```python
import os
from crypto_deep_research.mcp_server.server import build_server
from crypto_deep_research.mcp_server.sources.coingecko import source_from_env

if __name__ == "__main__":
    server = build_server(source_from_env(), host=os.environ.get("MCP_HOST"))
    server.run(transport="streamable-http")
```
- 이 코드는 "환경변수(설정 쪽지)를 읽어 서버를 조립하고 켠다"는 뜻이다. `python -m crypto_deep_research.mcp_server`로 실행되는 **정식 출입구(프로세스 엔트리)**이며, M5 패키징(docker-compose로 6개 프로그램 동시 가동)에서 이 경로가 쓰인다.
- **조립이 전부 env로 결정된다**: `COIN_DATA_SOURCE`(견본↔CoinGecko 선택, `source_from_env`가 해석)와 `MCP_HOST`(문을 여는 주소). 코드 수정도, 스위치 코드도, 별도 설정 파일도 아니고 설정 쪽지 두 장이면 끝. **M5 AC#2** "fixture→live 교체는 env-only"가 설명문(docstring)에 그대로 명시돼 있다.
- server.py의 `__main__` 블록과의 차이: 여기는 env를 읽고, 저기는 안 읽는다. "환경(바깥 설정)을 해석하는 곳"을 출입구 한 곳에 모으고, `build_server`는 받은 재료로 조립만 하는 순수한 함수로 남긴다.
- 리뷰 02 ④: 이 출입구는 전용 테스트가 없는데, 판단 로직 없이 부품을 끼우기만 하는 코드라 "spec상 무방"으로 합의됐다.

---

## 3. `sources/base.py` — DataSource Protocol: 출처의 계약

```python
from typing import Protocol
from crypto_deep_research.contracts.mcp_tools import OHLCV, News, OnchainMetrics, Orderbook

class DataSource(Protocol):
    def get_ohlcv(self, symbol: str, interval: str) -> OHLCV: ...
    def get_orderbook(self, symbol: str) -> Orderbook: ...
    def get_news(self, symbol: str) -> News: ...
    def get_onchain(self, symbol: str) -> OnchainMetrics: ...
```
- 이 코드는 "'코인 데이터 출처'라고 불리려면 이 4가지 일을 할 수 있어야 한다"는 **자격 요건서**다. 4가지 일은 도구 4개와 1:1로 대응한다.
- **왜 상속(ABC)이 아니라 Protocol인가**: contracts.md §5와 같은 이유다. 상속은 "특정 부모 클래스의 자식이어야 함"을 따지는 혈통 검사이고, Protocol은 "모양만 맞으면 인정"하는 구조적 타이핑이다. `FixtureSource`도 `CoinGeckoSource`도 이 클래스를 상속하지 않는다 — 메서드 4개의 모양만 맞으면 타입 검사기(mypy)가 합격 여부를 확인해 준다. [TECH-CHOICES.md](../TECH-CHOICES.md) §⑦의 비유: 채용할 때 "특정 학교 출신(상속)"이 아니라 "이 4가지 업무가 가능한 사람(자격 요건)"을 뽑는다.
- 파일 설명문이 이 파일의 존재 이유를 요약한다: "FixtureSource implements it day one; CoinGeckoSource swaps in at M5 with no agent code change (**the MCP boundary holds**)." — 즉 "첫날엔 견본이 이 자격을 채우고, M5에 CoinGecko가 들어와도 에이전트 코드는 한 줄도 안 바뀐다 (MCP 경계가 버틴다)". 출처 교체가 워커·오케스트레이터에게 전혀 안 보이는 것이, 경계가 제대로 섰다는 증거다. DESIGN.md 마일스톤 M5의 정의("Swap one fixture source for a live API behind the same MCP tool, no agent code changes")가 그대로 이 Protocol에 걸려 있다.
- 돌려주는 형식이 전부 contracts 모델: 출처가 무엇이든, 통신선(wire)에 실려 나가는 데이터의 모양은 같다.

---

## 4. `sources/fixture.py` — 견본 데이터 출처 (day one)

```python
_FIXTURES = Path(__file__).parent / "fixtures"
```
- 이 코드는 "견본 JSON 파일들이 든 폴더를, **이 소스 파일이 있는 위치 기준**으로 찾는다"는 뜻이다. 프로그램을 어느 폴더에서 실행하든(cwd, 현재 작업 폴더) — 내 컴퓨터든 컨테이너 안이든 — 항상 같은 fixtures 폴더를 찾는다. "실행한 자리 기준으로 길을 적어놨다가 다른 데서 실행하면 길을 잃는" 고전적 함정을 피한 것.

```python
class FixtureSource:
    def __init__(self, root: Path = _FIXTURES) -> None:
        self._root = root
```
- 이 코드는 "견본 폴더 위치(root)를 바깥에서 바꿔 끼울 수 있게 해둔다"는 뜻이다. 테스트가 임시 폴더의 가짜 견본을 쓸 수 있게 하는 최소한의 구멍이고, 기본값은 패키지에 같이 들어있는 fixtures.
- `DataSource`를 상속하지 않는 점에 주목 — Protocol(자격 요건)이므로 메서드 4개의 모양만 맞으면 된다.

```python
    def _load(self, symbol: str, tool: str) -> Any:
        path = self._root / f"{symbol.lower()}_{tool}.json"
        return json.loads(path.read_text(encoding="utf-8"))
```
- 이 코드는 "심볼과 도구 이름으로 파일명을 조립해 그 JSON 파일을 읽는다"는 뜻이다. 파일명 규약: `btc_ohlcv.json`, `btc_news.json`처럼 `{심볼}_{도구}.json`. 이름 짓는 규칙 하나 덕분에 도구 4개의 파일 읽기가 메서드 하나로 합쳐진다.
- 없는 심볼이면 `FileNotFoundError`(파일 없음 에러)가 그냥 터진다 — **일부러 잡지 않는다**. 이 에러는 워커의 data 노드에서 "이 항목은 데이터를 못 구했음"이라는 표시(dimension gap)로 변환된다(A3: 실패는 보고서의 데이터가 되지, 침묵하지 않는다). 리뷰 02 **S3**이 이 동작을 "BTC 한 종목만 다루는 이번 단계 목표(DoD) 안에서 의도된 한계"로 기록했다(견본 파일은 `btc_*.json`만 존재).

```python
    def get_ohlcv(self, symbol: str, interval: str = "1d") -> OHLCV:
        return OHLCV.model_validate(self._load(symbol, "ohlcv"))
```
- 이 코드는 "JSON 파일 내용을 **검사하면서** 정해진 서식(Pydantic 모델)에 옮겨 담는다"는 뜻이다. `model_validate`가 그 검사원 역할 — 견본 파일이 서식과 어긋나면 여기서 즉시 터진다. 견본조차 계약 검사를 통과해야 밖으로 나갈 수 있다.
- `interval`(캔들 간격: 일봉/주봉 같은 것) 파라미터를 받지만 쓰지 않는다: 견본은 간격 구분 없이 한 벌뿐이다. 자격 요건서(Protocol)의 모양을 맞추기 위해 받기만 하는 것이고, 견본에 간격별 버전을 다 만드는 것은 불필요한 정교화다.
- 나머지 3개 메서드도 같은 패턴 (도구 이름과 서식만 다름).

---

## 5. `sources/coingecko.py` — 라이브 출처 (M5) + 429 처리

### 배경: M5의 "한 도구만 라이브" 전략

M5의 목표는 "실제 API를 많이 연동하기"가 아니라 **"같은 MCP 도구 뒤에서 출처를 바꿔도 에이전트가 눈치채지 못한다"는 것의 증명**이다. 그래서 4개 도구 전부가 아니라 `get_ohlcv` **하나만** CoinGecko 실데이터로 가고, 나머지 3개는 견본에 그대로 맡긴다. 증명에는 하나면 충분하다 (Simplicity First). 파일 설명문: "The M5 live swap (AC#2) is this file + env only."

### 줄별 해설

```python
_BASE = "https://api.coingecko.com/api/v3"
_SYMBOL_TO_ID = {"BTC": "bitcoin", "ETH": "ethereum"}
_INTERVAL_TO_DAYS = {"1d": "1", "1w": "7", "1m": "30"}
_RETRIES = 2
_BACKOFF_BASE_S = 0.5
```
- 이 코드는 "CoinGecko와 대화할 때 쓸 주소·번역표·재시도 규칙을 한곳에 적어둔다"는 뜻이다.
- `_SYMBOL_TO_ID`: 우리 시스템은 심볼("BTC")로 말하지만 CoinGecko는 자기들만의 이름표(coin id, "bitcoin")로 말한다. 그 **번역표** — 이번 단계 범위(BTC, +ETH)만큼만 채워져 있다. 리뷰 02 **S3**: 표에 없는 심볼은 `symbol.lower()`(소문자로 바꾼 심볼)를 이름표로 추측하는데, 틀리면 404(그런 것 없음) 에러가 날 수 있음 → "BTC 한 종목이 이번 목표라 현행 허용, 한계를 글로 남기는 것이 최소 수정(surgical)"으로 결론.
- `_INTERVAL_TO_DAYS`: 우리 쪽 캔들 간격 표기(1d 등)를 CoinGecko가 알아듣는 `days` 값으로 바꾸는 번역표.
- 재시도 상수 2개가 파일 맨 위에 이름 붙어 있다 — 의미를 알 수 없는 숫자(매직 넘버)를 코드 본문 속에 묻어두지 않는다.

```python
def _retry_after(resp: httpx.Response, default: float) -> float:
    header = resp.headers.get("Retry-After")
    if header is None:
        return default
    try:
        return float(header)
    except ValueError:
        return default
```
- 이 코드는 "상대 서버가 '몇 초 뒤에 다시 와라'라고 적어준 쪽지(`Retry-After` 헤더)를 읽되, 쪽지가 없거나 숫자가 아니면 우리 기본 대기 시간을 쓴다"는 뜻이다.
- 배경: rate limit이란 "너무 자주 찾아오면 받아주지 않는다"는 상대 서버의 **방문 횟수 제한**이다(가게의 '1인 1개 한정' 같은 것). 그 제한에 걸렸을 때 **서버가 기다리라는 시간을 존중**하는 것이 정석 대응이다 (CLAUDE.md 프로젝트 맥락: "rate limit에 주의"). 헤더는 남의 서버가 보내는 외부 입력이라 무엇이든 적혀 올 수 있으므로, 숫자 변환 실패만큼은 방어한다 — 일어날 리 없는 시나리오가 아니라 실제로 일어나는 시나리오이기 때문.

```python
class CoinGeckoSource:
    def __init__(
        self, fixture: FixtureSource | None = None, client: httpx.Client | None = None
    ) -> None:
        self._fixture = fixture or FixtureSource()
        self._client = client or httpx.Client(timeout=10.0)
        self._api_key = os.environ.get("COINGECKO_API_KEY") or ""
```
- 이 코드는 "CoinGecko 출처를 만들 때, 부품 2개를 바깥에서 갈아 끼울 수 있게 한다"는 뜻이다. 부품은 `fixture`(일을 떠넘길 견본 출처)와 `client`(인터넷 요청을 보내는 전화기 역할의 HTTP 클라이언트). 테스트는 가짜 전화기를 꽂아 **실제 인터넷 호출 없이** 429 상황과 응답 해석을 검증한다 (`test_source_swap.py`, CLAUDE.md "테스트에서 CoinGecko 응답은 mock").
- `timeout=10.0`: 상대가 응답이 없으면 10초까지만 기다리고 끊는다 — 외부 API에 무한정 매달리지 않는다. 워커 전체 제한시간(A3, 30초) 안에 안전하게 들어오는 여유.
- API 키(서비스 이용 출입증)는 **env에서만** 읽는다(NFR#3 "키는 .env", 리뷰 02 ③에서 코드에 직접 적힌 키 없음 확인). 키가 없으면 빈 문자열 — CoinGecko의 무료(demo) 등급은 키 없이도 동작하므로 키를 필수로 강제하지 않는다.

```python
    def get_ohlcv(self, symbol: str, interval: str = "1d") -> OHLCV:
        coin_id = _SYMBOL_TO_ID.get(symbol.upper(), symbol.lower())
        params = {"vs_currency": "usd", "days": _INTERVAL_TO_DAYS.get(interval, "1")}
        headers = {"x-cg-demo-api-key": self._api_key} if self._api_key else {}
        rows = self._get_json(f"{_BASE}/coins/{coin_id}/ohlc", params, headers)
        bars = [
            OHLCVBar(ts=int(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=0.0)
            for r in rows
        ]
        return OHLCV(symbol=symbol.upper(), interval=interval, bars=bars)
```
- 이 코드의 흐름은: 심볼→CoinGecko 이름표로 번역 → 요청 조건 구성 → 인터넷으로 가져오기(HTTP GET) → CoinGecko가 주는 숫자 나열(`[시각, 시가, 고가, 저가, 종가]`)을 우리 공식 서식 `OHLCVBar`에 옮겨 담기.
- 출입증(API 키)을 **헤더**(`x-cg-demo-api-key`, 요청에 동봉하는 봉투 속 메모)로 보내고 주소(URL) 뒤에 붙이지 않는다 — 주소는 여기저기 기록(로그)에 남기 쉬우므로, 키가 새어 나갈 표면을 줄인다 (리뷰 02 ③에서 확인된 사항).
- **`volume=0.0` 고정값 — 리뷰 02 S2**: CoinGecko의 이 창구(`/coins/{id}/ohlc`)는 거래량을 안 준다. 지금의 market 워커는 시각과 종가만 쓰므로 무해하지만, 나중에 거래량 기반 판단이 생기면 조용히 "거래량 0"으로 오작동할 수 있는 지점이다. 리뷰 결론은 "설명문에 한계 명시 + 현행 유지"(개선하려면 `/market_chart`라는 다른 창구로 교체). **데이터의 빈칸을 숨기지 않고, 글로 남긴 한계로 만든 사례.**
- 마지막 줄에서 외부 응답이 contracts 서식으로 변환된다 — 실데이터든 견본이든 밖으로 나가는 모양은 동일(MCP 경계 유지).

```python
    def get_orderbook(self, symbol: str) -> Orderbook:
        return self._fixture.get_orderbook(symbol)
    # get_news, get_onchain 동일
```
- 이 코드는 "나머지 3개 도구는 견본 출처에 그대로 **떠넘긴다(위임)**"는 뜻이다 — 손님에게 보이는 창구 4개는 그대로 두면서(MCP tool surface unchanged), 실데이터 전환은 1개 창구에만 적용. 또 하나 주목할 점: CoinGeckoSource는 FixtureSource를 **부품으로 품는** 방식(합성, composition)이지 그 자식 클래스(상속)가 아니다.

```python
    def _get_json(self, url: str, params: dict[str, str], headers: dict[str, str]) -> Any:
        for attempt in range(_RETRIES):
            resp = self._client.get(url, params=params, headers=headers)
            if resp.status_code != 429:
                resp.raise_for_status()
                return resp.json()
            time.sleep(_retry_after(resp, _BACKOFF_BASE_S * 2**attempt))
        resp = self._client.get(url, params=params, headers=headers)
        resp.raise_for_status()  # a 429 on the final attempt raises -> dimension gap (AC#4)
        return resp.json()
```
- 이 코드는 "**429(너무 자주 왔음, rate limit) 응답만 특별 취급**해서 기다렸다 다시 가는 재시도 반복문"이다. 에러의 성격에 따라 대응이 다르다:
  - 429가 아닌 에러(404 없음, 500 서버 고장 등): 다시 가도 똑같을 가능성이 큰 경우 → `raise_for_status()`로 **즉시** 에러를 올린다.
  - 429: 일시적 혼잡 → 서버가 적어준 대기 쪽지(`Retry-After`, 없으면 0.5초→1.0초로 점점 길게 — 이를 **백오프**, 즉 "혼잡할수록 한 발 물러나 기다리기"라 한다)만큼 기다렸다 재시도, 총 2회.
- 반복문이 끝나면(=2번 다 429) **마지막으로 한 번 더** 시도하고, 그래도 429면 `raise_for_status()`가 에러를 던진다. 핵심은: 끝까지 막혔을 때 조용히 빈 데이터를 돌려주며 넘어가지 않고 **깨끗한 에러로 끝낸다**는 것.
- 그 에러가 어디로 가는지가 코드 주석에 적혀 있다: **M5 AC#4** — 워커의 data 노드가 이 에러를 받아 "이 항목은 비었음"(dimension gap) 표시로 변환하고(A3), 시스템은 부분(partial) 보고서를 낸다. 시스템이 죽지도, 모른 척하지도 않고 **"이 차원은 rate limit 때문에 비었음"이라는 데이터**가 된다. (`test_persistent_429_raises_clean_error` / `test_429_surfaces_as_dimension_gap`이 이 두 단계를 각각 검증.)
- MCP 서버 안에서 견본 데이터로 대체(fallback)하지 않는 이유: 실데이터를 달라고 했는데 견본을 몰래 돌려주면 "조용한 거짓"이 된다. 실패는 위로 올려 보내 보고서에 보이게 한다.

```python
def source_from_env() -> DataSource:
    """Pick the MCP server's data source from ``COIN_DATA_SOURCE`` (default ``fixture``)."""
    if os.environ.get("COIN_DATA_SOURCE", "fixture").lower() == "coingecko":
        return CoinGeckoSource()
    return FixtureSource()
```
- 이 코드는 "환경변수(설정 쪽지) 한 장으로 출처를 고르는 스위치"라는 뜻이다. **기본값이 fixture(견본)**라는 점이 중요 — 쪽지에 명시적으로 `coingecko`라고 적어야만 실데이터로 간다(라이브는 켜겠다고 선택해야 켜지는 옵트인). 출입증 없이, 인터넷 없이 띄워도 기본 동작이 안전하다.
- `"coingecko"` 외의 모든 값(오타 포함)은 견본으로 떨어진다 — 리뷰 02 ②에서 확인된 동작. `test_source_swap::test_source_from_env_swaps`가 "이 스위치 하나가 곧 M5 AC#2의 전부"임을 검증한다.
- 돌려주는 타입이 구체적인 클래스가 아니라 `DataSource`(자격 요건서, Protocol): 부르는 쪽(`__main__.py`)은 어느 쪽이 왔는지 영원히 모른다.

---

## 6. 관통하는 설계 원칙 요약

1. **무상태 + 읽기 전용이 동시성의 해법 (A4)** — 줄 세우기(잠금)도, 대기열도, 손님 기록도 없이 "기억하는 게 없으면 다툴 것도 없다"는 원리로 워커 4명의 동시 접속 문제를 구조적으로 없앤다. 모든 도구 호출 = 출처 읽고 돌려주기.
2. **경계는 표준 부품(SDK), 내용물은 직접 — 의도된 비대칭** — A2A는 손으로(A1, 통신 규약의 속 구조가 학습 대상), MCP는 FastMCP로(경계의 위치가 학습 대상). 무엇을 배우려는가에 따라 만들 것과 사 올 것을 가른다.
3. **출처는 자격 요건서(Protocol) 뒤에 숨긴다 (M5 AC#2)** — 도구 창구 4개는 불변, `DataSource` 구현만 환경변수로 교체. 견본→실데이터 전환이 `coingecko.py` + 설정 쪽지 두 장으로 끝나고 `workers/`·`orchestrator/`는 한 줄도 안 바뀐다. "the MCP boundary holds(MCP 경계가 버틴다)."
4. **실패는 위로, 깨끗하게 (A3 / M5 AC#4)** — 끝까지 막힌 429도, 없는 견본 파일도 에러로 위에 올려 보낸다. MCP 서버는 몰래 대체품을 내놓아 실패를 숨기지 않고, 워커가 그것을 "이 항목 비었음"(dimension gap)이라는 데이터로 바꿔 보고서에 남긴다.
5. **rate limit은 규칙대로 존중한다** — 429(방문 횟수 초과)만 골라 `Retry-After` 쪽지 + 점점 길어지는 대기(지수 백오프)로 재시도하고, 그 외 에러는 즉시 실패. 에러의 성격에 따라 대응을 달리한다.
6. **안전한 기본값, 명시적 선택(옵트인)** — 출처 기본은 견본, 접속 주소 기본은 내 컴퓨터 안(localhost + rebinding 잠금장치). 실데이터·외부 개방은 환경변수로 명시해야만 켜진다.
7. **한계는 고치는 대신 글로 남기기도 한다 (S2, S3)** — `volume=0.0`, BTC/ETH뿐인 번역표는 이번 단계 목표(DoD) 안의 의도된 한계다. 리뷰는 "코드 수정보다 한계를 글로 남기는 것이 최소 수정(surgical)"으로 결론냈다 — 모든 빈칸이 버그는 아니며, 기록된 빈칸은 빚이 아니라 지도다.
