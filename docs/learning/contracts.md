# 학습 자료: `contracts/` 패키지 완전 해부

> 대상: `crypto_deep_research/contracts/` 의 5개 모듈.
> 목적: 각 코드가 **무슨 의미**인지, **무슨 기능**인지, **왜 이렇게 설계했는지**를 한 줄 단위로 이해하기.
> 설계 결정 코드(A1, A2, C2, C5, TENSION-C)의 원 출처는 [docs/DESIGN.md](../DESIGN.md)의 결정 테이블.

---

## 0. 큰 그림: contracts란 무엇이고 왜 존재하나

이 시스템은 **6개의 독립 프로세스**로 구성된다. 여기서 "프로세스"란 **따로 돌아가는 프로그램**을 말한다 — 한 컴퓨터 안에 있어도 서로 남남인 별개 프로그램들이다:

```
오케스트레이터 ──A2A(JSON-RPC)──▶ 워커 4개 (market / orderbook / sentiment / onchain)
                                      │
                                      └──MCP──▶ 코인 데이터 MCP 서버
```

(역할로 보면: 오케스트레이터 = 전체를 지휘하는 팀장, 워커 = 시세·호가·여론·온체인을 각각 맡은 4명의 분석 담당자, MCP 서버 = 원본 데이터를 내주는 자료실.)

따로 돌아가는 프로그램끼리는 서로의 머릿속(메모리)을 들여다볼 수 없다. 그래서 소통은 오직 "주고받는 메시지"로만 이뤄지고, **그 메시지의 정해진 양식 — 이것이 "스키마(schema)"다 — 이 곧 시스템의 계약(contract)** 이 된다. 스키마란 쉽게 말해 **"주고받는 서류의 양식"** 이다: 어떤 칸이 있고, 각 칸에 어떤 종류의 값이 들어가야 하는지를 정해둔 것.
`contracts/` 패키지는 그 계약서 양식들을 Pydantic 모델로 한 곳에 모아두고, 6개 서비스가 전부 가져다 쓰는 **단일 진실 공급원(single source of truth)** — 즉 "양식의 원본 보관소"다. 모두가 복사본이 아닌 같은 원본을 보고 일한다.

**왜 이렇게? → 설계 결정 C5**: "Shared contracts — 6개 서비스가 모두 import하는 하나의 `contracts/` 패키지."
대안은 각 서비스가 양식을 복사해서 따로 갖는 것인데, 그러면 한쪽만 양식을 고쳤을 때 — 마치 계약서 갑·을이 서로 다른 버전의 계약서를 들고 있는 것처럼 — 메시지가 오가는 길목(wire) 위에서 조용히 깨진다. 양식 원본을 공유하면 양식이 바뀌는 순간 검사 도구(mypy/pytest)가 시스템 전체에서 한 번에 어긋난 곳을 잡아낸다.

**왜 Pydantic?** Pydantic은 "양식대로 작성됐는지 자동으로 검사해주는 도구"다. CLAUDE.md 규약("에이전트 상태는 typed schema — untyped dict 금지", 즉 "양식 없는 메모지 금지")이기도 하고, Pydantic은 다음 세 가지를 한 번에 해결한다: (1) **직렬화/역직렬화** — 프로그램 안의 데이터를 우편으로 보낼 수 있게 글자(JSON)로 포장하고, 받으면 다시 풀어내는 일, (2) **런타임 검증** — 실제로 데이터가 도착한 순간 "이 칸이 너무 길지 않은지" 등을 검사하는 일, (3) mypy 타입 체크 — 코드를 실행하기 전에 미리 하는 서면 검토. 메시지 길목(wire)을 넘는 데이터는 도착 시점 검사(런타임 검증)가 필수다 — 코드에 적어둔 타입 힌트는 "이래야 한다"는 메모일 뿐이라, 네트워크 바깥에서 들어온 엉뚱한 JSON을 실제로 막아주지는 못한다.

모듈 간 의존 방향 (한 방향, 순환 없음 — 즉 "A가 B를 참조하고 B가 다시 A를 참조하는" 꼬임이 없다):

```
mcp_tools.py   (독립 — MCP 도구 I/O)
artifact.py    (독립 — 워커 출력)
   ├─▶ a2a.py     (artifact를 JSON-RPC result로 운반)
   └─▶ report.py  (artifact의 Dimension/Evidence 재사용)
          └─▶ memory.py (report를 RunRecord에 보관)
```

---

## 1. `__init__.py` — 빈 패키지 초기화

```python
"""Shared contract schemas imported by all six services (C5).

Import from the submodules directly, e.g.
``from crypto_deep_research.contracts.artifact import WorkerArtifact``.
"""
```

- **의미**: 이 파일에는 설명문(docstring)만 있고 코드가 없다. `from contracts import WorkerArtifact`처럼 짧게 가져올 수 있는 지름길(재수출, re-export)을 일부러 만들지 않았다.
- **왜?**: 지름길을 만들면 같은 양식을 가져오는 경로가 두 개가 되어 "어디서 가져오는 게 정답인가"가 갈라진다. 항상 원래 위치(서브모듈)에서 직접 가져오게 강제하면, 텍스트 검색(grep) 한 번으로 그 양식을 쓰는 곳 전부를 빠짐없이 찾을 수 있다. (Simplicity First — 요청 없는 편의 기능 금지)

---

## 2. `artifact.py` — 워커가 내놓는 "증류된" 결과물

이 파일이 contracts의 심장이다. **설계 결정 A2(증류 강제)** 를 코드로 구현한 곳.

### 배경: 왜 "증류(distillation)"가 핵심인가

"증류"란 술을 증류하듯 **대량의 원료에서 핵심만 뽑아 농축하는 것** — 여기서는 방대한 원시 데이터를 짧은 요약으로 줄이는 일이다. 워커는 가격 캔들 1000행(OHLCV) 같은 대량 원시 데이터를 MCP로 받아 분석한다. 그 원시 데이터가 팀장(오케스트레이터)에게 그대로 흘러들어오면:
- 오케스트레이터 컨텍스트(LLM에게 주는 프롬프트, 즉 AI가 한 번에 읽어야 하는 분량)가 폭발한다 — 일을 여러 담당자에게 나눠 맡긴(멀티에이전트) 의미가 사라짐
- 합성(synthesis: 4명의 분석을 하나의 보고서로 종합하는 단계) 품질이 떨어진다 — 요약 대신 원시 숫자 더미를 읽게 됨

그래서 A2는 "워커는 **분량 상한이 박힌 요약물만** 반환할 수 있다"를 **스키마(양식) 수준에서 강제**한다. "워커야, 요약해서 보내줘"라고 말로 부탁하는 게 아니라, 보고서 양식 자체의 칸을 작게 만들어서 요약이 아니면 Pydantic 검증(양식 검사)을 **물리적으로 통과할 수 없게** 만든 것. (LLM에게 부탁 < 스키마로 강제 — 이 프로젝트의 핵심 교훈 중 하나)

### 줄별 해설

```python
Dimension = Literal["market", "orderbook", "sentiment", "onchain"]
```
- 이 코드는 "분석 차원은 이 4가지 말고는 존재하지 않는다"는 뜻 — 4종의 **닫힌 집합**이다. 아무 글자나 허용하는 `str`이 아니라 정해진 값만 허용하는 `Literal`인 이유: 오타("markets")가 도착 시점 검사와 사전 서면 검토(mypy) 양쪽에서 즉시 잡힌다. 워커가 4개로 고정된 시스템이므로 빈칸을 자유 기입란으로 열어둘 이유가 없다.

```python
class Evidence(BaseModel):
    metric: str = Field(max_length=64)   # 예: "RSI_14"
    value: float | str                   # 자기완결적 값 — 워커 컨텍스트로의 포인터 금지
```
- **의미**: "주장의 근거"를 `{지표명, 값}` 쌍으로 표현하는 양식. 예: `{"metric": "RSI_14", "value": 71.3}`.
- **왜 자유 텍스트가 아니라 정해진 칸 두 개인가?**: 근거가 "지표명 칸 + 값 칸"으로 구조화돼 있어야, 종합 단계에서 여러 담당자의 근거를 기계적으로 합치고 표로 보여줄 수 있다. 자유 서술이면 사람이 일일이 읽어야 한다.
- **`value`의 주석 "never a pointer into worker context"가 중요**: "자세한 건 내 쪽 자료의 532번 항목 참조" 같은 값은 금지라는 뜻. 오케스트레이터는 워커의 머릿속(메모리)을 읽을 수 없으므로(따로 돌아가는 프로그램이니까!), 값은 — 첨부 자료 없이도 읽히는 문장처럼 — 그 자체로 완결돼야 한다.

```python
class WorkerArtifact(BaseModel):
    dimension: Dimension
    status: Literal["ok", "failed"]
    headline: str = Field(max_length=200)
    key_points: list[str] = Field(max_length=5)            # 핵심 포인트 최대 5개 (A2)
    evidence: list[Evidence] = Field(default_factory=list, max_length=10)
```
- 이 코드는 워커가 제출하는 "분석 결과 보고서 양식"이다. 칸별로:
- `dimension`: 이 결과물이 어느 분석 차원 것인지. 팀장이 4장의 보고서를 모을 때 누가 낸 것인지 식별하는 이름표.
- `status`: 워커 스스로 적는 성공/실패 표시. 실패해도 **보고서는 제출된다**(에러를 던지며 자리를 비우는 게 아니라). 부분 실패도 데이터로 다루기 위함 — 아래 TENSION-C와 연결.
- `headline`: 한 줄 결론, 200자 상한.
- `key_points`: **최대 5개** — 여기서 `list`의 `Field(max_length=5)`는 목록의 항목 개수 제한이다(문자열 길이가 아님).
- `evidence`: 근거 최대 10개. `default_factory=list`인 이유 — Python에서 빈 목록(`[]`) 같은 "내용이 변할 수 있는 객체"를 기본값으로 직접 쓰면 모든 보고서가 같은 목록 하나를 공유하게 되는 고전적 함정이 있는데, 그것의 표준 회피법이다.

```python
    @field_validator("key_points")
    @classmethod
    def _cap_point_len(cls, v: list[str]) -> list[str]:   # 각 포인트 200자 이하
        if any(len(p) > 200 for p in v):
            raise ValueError("key_point exceeds 200 chars")
        return v
```
- 이 코드는 "핵심 포인트 한 줄 한 줄도 각각 200자를 넘으면 퇴짜"라는 뜻의 추가 검사기(validator)다.
- **왜 검사기가 따로 필요한가?**: `Field(max_length=5)`는 항목 **개수**만 제한한다. 항목 각각의 **글자 수**는 못 잡는다. 개수 제한만 있으면 워커가 "포인트는 5개지만 하나에 10만 자"를 욱여넣어 양식을 우회할 수 있다. 이 검사기가 그 구멍을 막는다.
- 결과적으로 보고서 전체 크기의 상한: 헤드라인 200 + 포인트 5×200 + 근거 10×(64+α) ≈ **수 KB로 수렴 보장**. 이게 A2의 "bounded(상한 있음)" 약속이고, 격리 테스트(1000행 OHLCV를 먹여도 artifact가 bounded이고 오케스트레이터 상태에 원시 배열이 0개임을 단언)가 이를 검증한다.

---

## 3. `a2a.py` — 에이전트 간(A2A) 통신의 wire 포맷

### 배경: 왜 JSON-RPC를 직접 손으로 만들었나 (설계 결정 A1)

- A2A(Agent-to-Agent)는 구글이 주도한 에이전트 간 통신 프로토콜이다. "프로토콜"이란 **서로 대화하는 절차와 형식의 약속** — 우편으로 치면 봉투 규격과 주소 쓰는 법이다. A2A의 전송 형식은 JSON-RPC 2.0(JSON으로 "이 함수를 이 인자로 실행해줘"라고 요청하는 오래된 표준 양식)이다.
- 선택지: 공식 `a2a` Python SDK(남이 만들어둔 완제품 라이브러리) vs 최소 JSON-RPC 직접 구현. **A1 = 직접 구현 선택.**
- **왜?**: 이 프로젝트의 목적은 학습이다. 완제품을 쓰면 프로토콜 내부가 블랙박스(뚜껑이 닫혀 안이 안 보이는 상자)가 되고, 실제로 필요한 건 "요청 하나, 응답 하나, Agent Card 하나"뿐이라 SDK가 끌고 오는 무게(스트리밍, 푸시 알림, 멀티턴 태스크...)가 전부 불필요하다. Simplicity First.
- **MCP와의 구분이 이 프로젝트의 핵심 학습 포인트**: MCP = 에이전트→**도구**(코인 데이터 서버에 자료 요청), A2A = 에이전트→**에이전트**(팀장이 담당자에게 업무 지시). 두 경계를 절대 섞지 않는다.

### 줄별 해설

```python
class TaskParams(BaseModel):
    symbol: str                                   # 분석 대상 코인 (예: "BTC")
    run_id: str                                   # 이번 실행의 고유 ID
    episodic_seed: dict[str, str] | None = None   # 오케스트레이터가 넘겨줄 수 있는 지난 실행 요약
```
- 이 코드는 팀장이 담당자에게 보내는 "업무 지시서 양식"이라는 뜻이다.
- `run_id`: 한 번의 분석에서 4개 워커에 동시에(병렬) 일을 시키므로, 흩어진 로그·메모리·응답을 "같은 실행 건"으로 묶을 사건 번호(상관관계 ID)가 필요하다.
- `episodic_seed`: 에피소드 메모리(지난 실행 기록)에서 꺼낸 요약을 워커에게 **선택적으로** 동봉하는 통로. `None` 허용 = 첫 실행이거나 기록이 없을 수 있음. 워커가 직접 기록 보관소(메모리 DB)를 뒤지지 않고 팀장이 필요한 만큼만 건네주는 이유: 기록의 소유권을 팀장에게 집중시켜 워커를 stateless(자기 기억 없이, 받은 지시서만으로 일하는 상태)로 유지하기 위함이다.

```python
class JsonRpcRequest(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str
    method: Literal["analyze"]
    params: TaskParams
```
- 이 코드는 JSON-RPC 2.0 표준 봉투 그대로라는 뜻: `jsonrpc`는 봉투 규격 버전 표식, `id`는 요청과 응답을 짝짓는 접수 번호, `method`는 시킬 일의 이름, `params`는 위의 업무 지시서.
- `jsonrpc: Literal["2.0"] = "2.0"`: 타입이 "2.0"만 허용하는 Literal이라 다른 값은 검증 실패 + 기본값이 있어 만들 때 안 적어도 자동으로 채워짐. 한 줄로 "항상 2.0이고 다른 값은 거부" 달성.
- `method: Literal["analyze"]`: 이 시스템의 워커가 할 줄 아는 일은 **analyze 하나뿐**. 닫힌 Literal로 못 박아 모르는 작업 요청을 양식 검사 단계에서 차단. (할 일이 늘어나면 그때 Literal에 추가 — 미리 일반화하지 않음)

```python
class JsonRpcError(BaseModel):
    code: int
    message: str

class JsonRpcResponse(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str
    result: WorkerArtifact | None = None
    error: JsonRpcError | None = None
```
- 이 코드는 워커가 돌려보내는 "회신 봉투 양식"이라는 뜻. JSON-RPC의 규약상 회신에는 `result`(성과물) **아니면** `error`(오류 통지) 중 하나만 채워진다(상호배타 — 둘 다 채우거나 둘 다 비우면 안 됨). `id`는 요청의 접수 번호를 그대로 돌려줘 어느 요청의 답인지 짝을 맞춘다.
- **여기가 A2와 A1이 만나는 지점**: `result` 칸의 타입이 `WorkerArtifact`다. 즉 **회신 양식 자체가 "워커는 증류된 요약 보고서 외엔 아무것도 반환할 수 없다"를 강제**한다. 워커가 원시 데이터를 흘리고 싶어도 봉투에 그걸 넣을 칸이 없다.
- "둘 중 하나만"을 별도 검사기로 강제하지 않은 것은 의도적 단순화 — 회신을 만드는 쪽 코드가 어차피 둘 중 하나만 채우며, 일어날 수 없는 시나리오용 방어 코드는 안 짠다는 원칙.

```python
class AgentCard(BaseModel):   # /.well-known/agent.json 에서 서빙
    name: str
    description: str
    url: str
    version: str
    skills: list[str]         # 예: ["analyze:market"]
```
- **Agent Card** = A2A 프로토콜의 "에이전트 명함". 각 워커 서비스가 `/.well-known/agent.json` 주소(웹 표준 "잘 알려진 위치" 관행 — 명함을 항상 같은 자리에 비치해두는 것)에서 자기소개를 내건다: 나는 누구고, 어디에 있고, 무슨 기술(`analyze:market`)을 제공하는가.
- 이 프로젝트에선 명함 내용이 **정적**(고정)이다. 동적 디스커버리(명함을 읽고 다닐 워커를 자동으로 찾아내는 것)는 v1 범위 밖 — 워커 4개의 주소는 설정 파일에 고정돼 있다. 그런데 왜 만들었나? A2A 프로토콜의 구성요소를 실제로 갖춰보는 것 자체가 학습 목표이기 때문(decision A1의 "static Agent Card").

---

## 4. `report.py` — 오케스트레이터의 최종 합성 보고서

### 배경: TENSION-C — "부분 실패를 숨기지 마라"

워커 4명 중 1명이 제시간에 답을 못 줘도(타임아웃) 시스템은 보고서를 내야 한다(전체 실패가 아니므로). 그런데 그 보고서가 멀쩡한 완성본처럼 보이면, 읽는 사람은 "4개 차원을 전부 본 분석 결과"로 오해한다. **TENSION-C 결정**: 최종 보고서는 차원별 커버리지(무엇을 봤고 무엇을 못 봤는지)를 **명시적인 칸으로** 운반하고, CLI(명령줄 화면)가 그것을 표시하며, "4개 중 1개만 성공한 실행은 눈에 보이게 partial(부분 성공)로 표시된다"는 테스트가 존재해야 한다. (A3 "조용한 실패 금지" 규칙을 "전부 실패" 케이스에서 "일부 실패" 케이스로 확장한 것)

### 줄별 해설

```python
class DimensionGap(BaseModel):
    dimension: Dimension
    reason: str        # 예: "timeout", "mcp_down"
```
- 이 코드는 "빠진 차원 신고 양식"이라는 뜻: **어느** 차원이 **왜** 빠졌나. 이유가 자유 문자열인 건 사람이 읽을 진단 메모이기 때문(프로그램이 이 값을 보고 동작을 분기하지 않으므로 Literal로 닫지 않음).

```python
class SynthesisReport(BaseModel):
    symbol: str
    status: Literal["ok", "partial", "failed"]
    headline: str = Field(max_length=200)
    key_points: list[str] = Field(max_length=10)
    evidence: list[Evidence] = Field(default_factory=list)
    dimensions_ok: list[Dimension]
    dimensions_unavailable: list[DimensionGap]   # TENSION-C
```
- 이 코드는 팀장이 4장의 보고서를 종합해 내는 "최종 보고서 양식"이라는 뜻이다.
- `status`가 워커의 2값(`ok|failed`)과 달리 **3값**: 종합 단계에만 존재하는 상태인 `partial`(일부 차원만 성공)이 추가된다. 4/4 성공 = ok, 1~3/4 = partial, 0/4 = failed.
- `key_points`가 워커(5개)의 두 배인 **10개**: 4개 차원을 합치는 보고서이므로 상한이 더 크지만, 여전히 상한이 있다(증류 원칙은 종합 단계에도 적용).
- `dimensions_ok` + `dimensions_unavailable`: 이 두 목록을 합치면 항상 4개 차원 전체가 되도록 하는 게 의도. 보고서만 봐도 "무엇을 근거로 했고 무엇이 빠졌는지"가 — 별도 문의 없이 — 자기완결적으로 드러난다.
- `Dimension`, `Evidence`를 artifact.py에서 **재사용**: 같은 개념에는 같은 타입을 쓴다는 뜻. 워커가 적은 근거가 최종 보고서로 옮겨질 때 양식 변환 없이 그대로 흘러갈 수 있다.

---

## 5. `memory.py` — 3층 메모리의 인터페이스(Protocol)

### 배경: 왜 Pydantic이 아니라 Protocol인가

이 파일의 세 메모리 클래스는 **데이터의 모양이 아니라 행위(할 수 있는 일의 목록)의 계약**이다. 양식(Pydantic)이 "서류에 어떤 칸이 있나"의 약속이라면, Python의 `typing.Protocol`은 "이 직무를 수행할 수 있는 사람이면 누구든 OK"라는 **직무기술서** 같은 것이다 — "이 메서드들을 가진 객체면 무엇이든 통과"라는 구조적 타이핑(혈통·상속을 따지지 않고 실제 능력만 보는 덕 타이핑을, 실행 전에 mypy가 서면으로 검사할 수 있게 한 버전)이다. 덕분에 구현(저장을 SQLite 파일로 하든 메모리에 임시로 하든)을 계약에서 분리해, 테스트에서 가짜 구현으로 갈아끼우기 쉽다.

3층 구조는 에이전트 메모리의 표준 분류를 따른다:

| 층 | 수명 | 이 시스템에서 |
|---|---|---|
| Working (작업) | 실행 1회 동안 | LangGraph 상태/checkpointer |
| Episodic (에피소드) | 실행 간, 심볼별 | "지난번 BTC 분석 결과" |
| Long-term (장기) | 영구 | 관심목록, 심볼별 누적 사실 |

(사람으로 치면: 작업 메모리 = 일하는 동안의 책상 위 메모, 에피소드 메모리 = "지난번 그 건 어땠더라" 업무 일지, 장기 메모리 = 오래 쌓아온 지식 노트.)

### 줄별 해설

```python
class RunRecord(BaseModel):
    run_id: str
    symbol: str
    ts: int                    # 타임스탬프
    report: SynthesisReport
```
- 이 코드는 에피소드 메모리(업무 일지)에 저장되는 한 페이지 = "한 번의 실행 기록"이라는 뜻. 최종 보고서를 통째로 담는다. 다음 실행에서 `episodic_seed`(a2a.py)로 동봉할 요약의 원재료가 된다. 이건 행위가 아니라 데이터(서류)라서 Protocol이 아닌 BaseModel.

```python
class WorkingMemory(Protocol):
    """구현은 checkpointer(memory/working.py)로 대체 — note/read는 미사용 (C2)."""
    def note(self, run_id: str, key: str, value: str) -> None: ...
    def read(self, run_id: str) -> dict[str, str]: ...
```
- **솔직한 역사적 흔적**: M0 단계에서 계약(직무기술서)을 먼저 정의했는데, 실제 구현 시점에는 작업 메모리 역할을 LangGraph의 checkpointer + 그래프 상태가 자연스럽게 대신하게 됐다. 그래서 이 Protocol을 실제로 수행하는 구현체는 없다(orphan — 주인 없는 계약). 코드 리뷰에서 발견되어(**C2** 이슈), 지우는 대신 설명문(docstring)으로 사실을 기록하는 쪽을 택했다 — M0 시점 계약의 형태를 보존하는 것도 학습 가치이기 때문.
- 메서드 끝의 `...`: Protocol의 메서드는 "이런 일을 할 수 있어야 한다"는 항목만 적고 실제 내용(본문)은 없다는 관례 표기.

```python
class EpisodicMemory(Protocol):
    def last_for(self, symbol: str) -> RunRecord | None: ...   # 읽기: 실행 시작 시
    def put(self, record: RunRecord) -> None: ...              # 쓰기: 실행 종료 시
```
- 이 코드는 업무 일지의 직무기술서: "마지막 기록 한 장 꺼내기"와 "새 기록 한 장 넣기", 딱 두 가지.
- 인터페이스(할 수 있는 일의 목록)가 의도적으로 좁다: 어떤 코인의 **마지막** 기록 하나만 읽는다(`last_for`). 전체 이력 검색 같은 건 v1에 필요 없으므로 없다. `None` = 그 코인의 첫 실행이라 기록이 없음.
- 주석이 **읽기/쓰기 시점**을 명시: 누가 언제 이 메서드를 부르는지도 계약의 일부다(읽기는 실행 시작, 쓰기는 실행 끝 — 오케스트레이터만 접근).

```python
class LongTermMemory(Protocol):
    def watchlist(self) -> list[str]: ...                             # 읽기: 플래너
    def facts(self, symbol: str) -> list[str]: ...                    # 읽기: 플래너
    def add_facts(self, symbol: str, facts: list[str]) -> None: ...   # 쓰기: 실행 종료 시
```
- 이 코드는 장기 지식 노트의 직무기술서라는 뜻. 두 종류의 지식을 다룬다: `watchlist`(추적 중인 코인 목록), `facts`(코인별로 누적된 사실 — "BTC는 2024년 반감기 이후..."). 플래너(실행 계획을 세우는 부분)가 계획을 세울 때 읽고, 실행이 끝나면 새로 알게 된 사실을 추가한다.
- `add_facts`(추가)만 있고 삭제/수정이 없다 — append-only(덧붙이기만 가능한 장부). 필요해질 때까지 만들지 않는다.

---

## 6. `mcp_tools.py` — MCP 도구의 입출력 스키마

### 배경

MCP(Model Context Protocol) 서버 — 에이전트가 외부 도구·자료를 쓸 수 있게 해주는 표준 창구 — 가 제공하는 4개 도구(`get_ohlcv`, `get_orderbook`, `get_news`, `get_onchain`)의 **반환 데이터 양식**이다. 워커 4명이 각자 자기 담당 도구를 호출한다 (market→OHLCV, orderbook→Orderbook, sentiment→News, onchain→OnchainMetrics).

이 양식들에는 분량 제한이 **없다**. artifact.py와 정반대인 것이 의도적이다: **MCP 경계(자료실→담당자)로는 원시 데이터가 아무리 크게 흘러들어와도 되고, A2A 경계(담당자→팀장)에서는 증류된 요약만 나간다.** 두 경계의 비대칭이 이 아키텍처의 요점이다. 1000행짜리 가격 데이터는 여기(자료실→담당자)서는 합법, 보고서(artifact)에 실으면 불법.

### 줄별 해설

```python
class OHLCVBar(BaseModel):
    ts: int          # 캔들 시각
    open: float; high: float; low: float; close: float; volume: float

class OHLCV(BaseModel):
    symbol: str
    interval: str    # 캔들 간격, 예: "1h"
    bars: list[OHLCVBar]
```
- 이 코드는 가격 차트 데이터의 양식이라는 뜻. OHLCV = 시가·고가·저가·종가·거래량, 즉 가격 차트의 캔들(막대) 하나에 적히는 다섯 숫자. `bars` 목록에 개수 상한 없음(위 설명대로 의도).

```python
class OrderbookLevel(BaseModel):
    price: float
    size: float

class Orderbook(BaseModel):
    symbol: str
    bids: list[OrderbookLevel]   # 매수 호가
    asks: list[OrderbookLevel]   # 매도 호가
```
- 이 코드는 호가창(사겠다/팔겠다 주문이 줄 서 있는 판) 데이터의 양식이라는 뜻. 호가 한 단계 = (가격, 수량). 매수/매도 벽, 스프레드(매수·매도 호가 간격) 분석의 원재료.

```python
class NewsItem(BaseModel):
    title: str
    source: str
    sentiment: float    # -1.0(매우 부정) .. 1.0(매우 긍정)

class News(BaseModel):
    symbol: str
    items: list[NewsItem]
```
- 이 코드는 뉴스 데이터의 양식인데, 핵심은 감성 점수(긍정/부정 정도)가 **도구 쪽에서 이미 계산돼** 들어온다는 계약이라는 뜻. sentiment 워커는 점수들을 종합·해석하는 역할이지, 기사 본문을 읽고 감성을 추출하는 역할이 아니다. 기사 본문 칸이 아예 없는 것도 같은 이유 — 본문을 넘기면 워커가 읽어야 할 분량(컨텍스트)이 부풀고, prompt injection 표면(외부에서 온 텍스트가 AI에게 주는 지시문 안으로 흘러들어가 AI를 조종하려 들 수 있는 접촉 면적)도 커진다.

```python
class OnchainMetrics(BaseModel):
    symbol: str
    active_addresses: int       # 활성 주소 수 (네트워크 사용 활성도)
    tx_volume: float            # 트랜잭션 볼륨
    exchange_netflow: float     # 거래소 순유입 (양수=입금 우세→매도 압력 신호로 해석되곤 함)
```
- 이 코드는 온체인(블록체인 장부에서 직접 읽은) 지표의 양식이라는 뜻. 다른 셋과 달리 목록이 아닌 **현재 시점 스냅샷 한 장**이다. 온체인 분석 v1에는 과거 흐름(시계열)이 아닌 현재 지표 3개면 충분하다고 본 것.

---

## 7. 관통하는 설계 원칙 요약

1. **경계마다 스키마, 스키마는 한 곳에 (C5)** — 프로그램 간 경계를 넘는 모든 데이터는 이 패키지의 Pydantic 양식을 따른다. 양식 없는 자유 메모(untyped dict)가 메시지 길목(wire)을 넘는 일이 없다.
2. **부탁하지 말고 강제하라 (A2)** — "요약해줘"라는 프롬프트(말) 대신 `max_length` + 검사기(양식의 작은 칸). LLM의 협조에 기대지 않고 타입 시스템이 증류를 보장한다.
3. **두 경계의 비대칭** — MCP(자료실→담당자)는 무제한 원시 데이터, A2A(담당자→팀장)는 상한 있는 증류물. `mcp_tools.py`에 제한이 없고 `artifact.py`에 제한이 빽빽한 이유.
4. **실패는 데이터다 (TENSION-C)** — `status: "failed"`인 artifact, `dimensions_unavailable` 칸. 예외를 던져 숨기는 대신 양식 안에 실패를 적을 자리를 만들어, 부분 실패가 보고서에 눈에 보이게 남도록 한다.
5. **닫을 수 있는 건 Literal로 닫는다** — `Dimension`, `method`, `status`, `jsonrpc`. 유효한 값이 몇 개로 정해져 있으면 자유 기입란으로 열어두지 않는다.
6. **행위 계약은 Protocol, 데이터 계약은 BaseModel** — memory.py(직무기술서: 할 수 있는 일의 목록) vs 나머지(서류 양식: 데이터의 모양). 구현 교체 가능성과 데이터 검증이라는 서로 다른 요구에 맞는 도구.
7. **필요해질 때까지 만들지 않는다** — 메서드 1개짜리 RPC, 고정 내용의 Agent Card, 덧붙이기만 되는 장기 메모리, 지름길 없는 `__init__`. 모두 "지금 필요한 최소"의 흔적.
