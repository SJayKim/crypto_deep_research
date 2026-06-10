# 학습 자료: `orchestrator/` 패키지 완전 해부

> 대상: `crypto_deep_research/orchestrator/` 의 4개 모듈 (app / planner / dispatch / synthesize).
> 목적: 각 코드가 **무슨 의미**인지, **무슨 기능**인지, **왜 이렇게 설계했는지**를 한 줄 단위로, 개발을 모르는 사람도 따라올 수 있게 이해하기.
> 설계 결정 코드(P9, A2, A3, TENSION-B, TENSION-C, AC#7)의 원 출처는 [docs/DESIGN.md](../DESIGN.md)의 결정 테이블, 리뷰 이슈(O1, O2)는 [docs/reviews/03-orchestrator.md](../reviews/03-orchestrator.md).
> 스키마(`WorkerArtifact`, `SynthesisReport`, `DimensionGap`, `JsonRpcRequest` 등)는 [contracts.md](contracts.md)에서 이미 다뤘으므로 여기서는 참조만 한다.

---

## 0. 큰 그림: 오케스트레이터는 무엇을 하나

이 시스템을 회사 팀에 비유하면 이렇다. **오케스트레이터 = 팀장**, **워커 = 전문 분야가 다른 팀원 4명**(시세 담당, 호가창 담당, 여론 담당, 블록체인 담당). 사용자가 "BTC 분석해줘"라고 하면 팀장이 일을 받아서 세 단계로 처리한다:

```
plan ──▶ dispatch ──▶ synthesize
 │          │             │
 │          │             └─ artifact들을 SynthesisReport로 합성 (TENSION-C)
 │          └─ 선택된 워커들에 A2A 병렬 호출 (P9: asyncio.gather)
 └─ Agent Card로 워커 발견 + 장기 메모리 읽고 워커 집합 결정 (TENSION-B)
```

- **plan(계획)**: 팀장이 팀원들의 명함(Agent Card)을 보고 누가 무슨 일을 하는지 파악한 뒤, 자기 수첩(장기 메모리)을 펼쳐 "이번 건은 누구누구한테 시킬지"를 정한다.
- **dispatch(분배)**: 정해진 팀원들에게 일을 **동시에** 시킨다. 한 명씩 순서대로 전화하는 게 아니라, 단체로 동시에 업무요청서를 보내는 방식이다(이것이 "병렬 디스패치").
- **synthesize(합성)**: 팀원들이 보낸 요약 보고(artifact)를 모아 하나의 최종 보고서(SynthesisReport)로 묶는다.

세 단계는 LangGraph라는 도구의 **선형 그래프**(plan→dispatch→synthesize)로 짜여 있다. 여기서 "상태 그래프"란 *작업 순서도 + 단계 사이에 넘겨주는 서류철*이라고 보면 된다 — 각 단계가 끝나면 결과를 서류철에 끼우고 다음 단계로 넘긴다. 갈림길도 되돌아가는 길도 없다. 이 단계까지 필요한 흐름이 일직선이기 때문에 일부러 직선으로만 만들었다(Simplicity First).

핵심 제약 두 가지가 모든 코드를 관통한다:

1. **격리(A2)**: 팀장의 서류철에는 팀원이 정리해 준 **요약본(artifact)만** 들어온다. 팀원이 작업 중에 뒤적인 원자료(예: 시세 1000행짜리 표)는 절대 팀장 책상에 올라오지 않는다. app.py의 설명문(docstring)이 이를 명시한다: *"Orchestrator state holds only distilled artifacts -- never a worker's raw context (A2)"*.
2. **실패는 데이터(A3 + TENSION-C)**: 팀원이 잠수를 타거나 일이 늦어져도 전체 업무가 멈추지 않는다. 프로그래밍에서 "예외"란 작업 도중 울리는 비상벨 같은 것인데, 이 시스템에서는 비상벨이 위로 울려 퍼지는 대신 "이 항목은 못 받았음"이라는 메모(`DimensionGap`)로 바뀌어 보고서의 `dimensions_unavailable` 칸에 기록된다. 즉 실패도 보고서의 한 줄이 된다.

파일별 역할:

| 파일 | 역할 | 핵심 결정 |
|---|---|---|
| `app.py` | LangGraph 그래프 조립 + 실행 수명주기(메모리 읽기/쓰기) | A2, M4 메모리 트리거 |
| `planner.py` | Agent Card 발견 + 장기 메모리 기반 워커 선택 | TENSION-B, AC#7 |
| `dispatch.py` | A2A JSON-RPC 호출 + 병렬 fan-out + 타임아웃→gap | P9, A3 |
| `synthesize.py` | artifact 병합 → 커버리지 명시 보고서 | TENSION-C |

---

## 1. `dispatch.py` — A2A 호출과 병렬 fan-out

먼저 dispatch부터 보는 이유: 이 파일에 이 프로젝트의 가장 중요한 아키텍처 결정(P9)이 들어 있다.

### 배경: 왜 LangGraph `Send`가 아니라 `asyncio.gather`인가 (설계 결정 P9)

LangGraph에는 `Send`라는 내장 기능이 있다 — 한 단계에서 여러 작업으로 동시에 갈라지게 해 주는 장치다. "LangGraph를 쓰는데 왜 그 기능을 안 쓰지?"가 자연스러운 의문이다.

**P9 결정의 원문**(DESIGN.md 결정 테이블): *"`asyncio.gather` over A2A. **NOT** LangGraph `Send` — `Send` dispatches in-graph nodes inside the orchestrator process and cannot cross the A2A boundary; using it silently collapses Approach B into Approach A."*

풀어 쓰면 이렇다. `Send`는 **같은 사무실 안에서** 일을 나눠주는 도구다. 그런데 이 시스템의 팀원(워커)들은 **각자 다른 건물에서 일하는 별도 프로그램**(별도 프로세스의 A2A 서버)이다. `Send`로 팀원을 부르려면 팀원들을 전부 팀장 사무실로 불러들여야 하는데, 그 순간 "각자 다른 건물 + 진짜 통신 규약으로 대화"라는 이 설계(Approach B)의 존재 이유 — 서로의 작업물이 섞이지 않게 건물 자체를 분리하고, A2A 통신을 실제로 연습한다 — 가 조용히 무너져 "한 사무실 시뮬레이션"(Approach A)이 돼버린다. 그래서 일 나눠주기는 그래프 기능이 아니라 평범한 **인터넷 동시 호출**로 한다. 여기서 `asyncio.gather`란 "여러 통화를 동시에 걸어놓고 전부 끝날 때까지 기다리는" 파이썬의 기본 도구다(asyncio는 "기다리는 동안 다른 일을 하게 해주는" 파이썬의 동시 작업 장치). "프레임워크에 기능이 있다 ≠ 그걸 써야 한다"의 교과서적 사례.

### 줄별 해설

```python
DEFAULT_TIMEOUT_S = 30.0
```
- 이 코드는 "기본 제한시간은 30초"라는 뜻. 타임아웃이란 *답을 기다려주는 최대 시간*이다 — 전화를 걸고 30초간 안 받으면 끊고 다음 일을 보는 것과 같다. A3 결정의 "per-worker 30s timeout (env-configurable)"의 기본값으로, 호출하는 쪽이 따로 값을 안 주면 30초가 적용된다.

```python
async def dispatch_one(
    worker_url: str, symbol: str, run_id: str,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    episodic_seed: dict[str, str] | None = None,
) -> WorkerArtifact:
    request = JsonRpcRequest(
        id=run_id,
        method="analyze",
        params=TaskParams(symbol=symbol, run_id=run_id, episodic_seed=episodic_seed),
    )
```
- **의미**: 워커 한 명에게 보낼 업무요청서(JSON-RPC 요청 — 정해진 양식의 서류라고 보면 된다)를 작성하는 코드다. M2(워커 한 명만 있던 시절)부터 있던 함수로, 이후의 fan-out은 이 함수를 여러 개 동시에 띄우는 것뿐이다.
- `id=run_id`: 요청서와 답장을 짝지을 일련번호 칸에 "이번 실행 ID"를 그대로 재사용한다. 별도 번호 체계를 만들지 않은 단순화 — 한 번의 실행에서 워커 한 명당 요청서가 한 장뿐이므로 그걸로 충분하다.
- `episodic_seed`: 팀장이 읽어 둔 "지난 실행 요약"을 워커에게 그대로 전달하는 통로(contracts.md의 `TaskParams` 참조). "지난번엔 이런 결론이었어요"라는 쪽지를 요청서에 첨부하는 셈.

```python
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        http_response = await client.post(worker_url, json=request.model_dump())
    response = JsonRpcResponse.model_validate(http_response.json())
```
- 이 코드는 "요청서를 인터넷으로 보내고 답장을 받는다"는 뜻. `httpx.AsyncClient(timeout=timeout_s)`는 통신의 각 단계(연결, 읽기, 쓰기)마다 제한시간을 거는 장치다. **주의 — 이것만으로는 "전체 30초 안에 끝"이라는 보장이 아니다**(아래 O1 참조).
- `model_dump()` / `model_validate()`: 보내는 서류와 받는 답장 모두 Pydantic이라는 **양식 검사기**를 통과한다. 워커 쪽에 버그가 있거나 누가 이상한 답을 보내도, **정해진 양식에 맞는 모양의 데이터만** 팀장에게 들어온다. 리뷰 03의 보안 체크 항목: *"악의적 worker 응답도 스키마 경계 통과분만 수용"*.

```python
    if response.error is not None or response.result is None:
        message = response.error.message if response.error else "empty result"
        raise RuntimeError(f"worker {worker_url} returned a JSON-RPC error: {message}")
    return response.result
```
- 답장은 "결과(result)" 아니면 "오류(error)" 둘 중 하나다. 오류이거나 결과 칸이 비어 있으면 예외(비상벨)를 울린다.
- "어? 실패는 데이터라며 왜 비상벨을 울리지?": **역할 분담**이다. `dispatch_one`은 "한 번의 통화"를 담당하는 낮은 층의 함수라서 실패를 비상벨로 알린다. 그 비상벨을 "이 항목 못 받았음" 메모(`DimensionGap`)로 **번역**하는 건 한 층 위의 `_dispatch_or_gap`이 맡는다. 이렇게 나누면 통화 한 건만 테스트할 때(M2)는 비상벨을 그대로 볼 수 있고, 여러 명에게 동시에 일을 시킬 때는 위층이 흡수한다.
- `return response.result`: 돌려주는 값의 타입이 `WorkerArtifact`(워커의 요약 보고). 답장 양식 자체(`JsonRpcResponse.result: WorkerArtifact | None`)가 이미 모양을 보장하므로 추가 검사가 없다 — 양식(contracts)이 일을 다 해놨다.

```python
async def _dispatch_or_gap(
    dimension: Dimension, worker_url: str, symbol: str, run_id: str,
    timeout_s: float, episodic_seed: dict[str, str] | None,
) -> WorkerArtifact | DimensionGap:
    try:
        return await asyncio.wait_for(
            dispatch_one(worker_url, symbol, run_id, timeout_s, episodic_seed),
            timeout_s,
        )
```
- **이 함수가 A3(실패 모델)의 구현체**: 결과는 요약 보고(artifact) **아니면** 결손 메모(gap), 비상벨(예외)은 절대 바깥으로 새어나가지 않는다. 함수 머리의 `WorkerArtifact | DimensionGap`이라는 표기가 그 약속을 글로 박아둔 것이다.
- `asyncio.wait_for(..., timeout_s)`: **리뷰 O1의 수정 결과**다. 원래는 통신 단계별 제한시간만 있었는데, 리뷰가 구멍을 찾았다: *"read 타임아웃 미만으로 바이트를 조금씩 흘리는 worker는 총 wall-clock을 초과할 수 있음"* — 비유하면, "한 문장당 29초 안에만 말하면 되지?"라며 29초마다 한 글자씩 말하는 사람은 단계별 제한은 안 걸리면서 통화를 한없이 끌 수 있다. 그러면 "워커당 30초"라는 약속이 깨진다. 권장 해법 (b) *"asyncio.wait_for로 worker당 단일 마감 보장"* 이 채택되어, 이제 단계별 제한시간(httpx)과 **손목시계로 재는 통화 전체 마감**(`wait_for`, 이것이 wall-clock 마감)이 **이중**으로 걸려 있다. docstring의 *"a single per-worker wall-clock deadline (A3) enforced by `asyncio.wait_for`"* 가 수정 후 문구.

```python
    except (TimeoutError, httpx.TimeoutException):  # wall-clock (A3) or HTTP-op timeout -> gap
        return DimensionGap(dimension=dimension, reason="timeout")
    except Exception as exc:  # unreachable / transport / bad envelope -> a gap, never raise
        return DimensionGap(dimension=dimension, reason=f"unreachable: {type(exc).__name__}")
```
- 두 갈래의 사고 처리: 시간 초과 계열(두 가지 제한시간 장치 각각이 울리는 비상벨)은 `reason="timeout"` 메모로, 그 외 모든 사고(연결 거부, 답장 깨짐, 양식 위반, `dispatch_one`이 울린 RuntimeError...)는 `reason="unreachable: <사고 종류 이름>"` 메모로 바꾼다.
- `except Exception`(= "어떤 사고든 전부 잡는다")은 보통 나쁜 습관으로 꼽히지만 여기서는 **의도된 설계**다. 이 단계의 철칙이 "어느 팀원의 어떤 사고도 다른 팀원의 일을 못 막는다"이기 때문이다. 한 워커의 비상벨이 그대로 울리면 `asyncio.gather`는 기본 동작상 **전체 작업을 중단**시킨다. 그 가능성을 원천 차단하는 자리가 바로 여기다. 주석 *"never raise"* 가 그 약속의 선언.
- `reason`에 사고 종류 이름을 넣는 것: 나중에 사람이 읽고 원인을 짐작할 진단 정보(contracts.md의 `DimensionGap.reason`이 자유 문자열인 이유와 동일).
- 이 함수의 `dimension`(분석 차원: 시세/호가창/여론/온체인 중 하나) 파라미터를 주목 — `dispatch_one`은 자신이 누구에게 전화하는지(주소)만 알지 그게 무슨 담당인지는 모른다. "어느 항목이 빠졌는지" 메모를 쓰려면 담당 정보가 필요하므로, 이 한 층 위의 포장 함수가 dimension을 들고 다닌다.

```python
async def fan_out(
    plan: dict[Dimension, str], symbol: str, run_id: str,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    episodic_seed: dict[str, str] | None = None,
) -> list[WorkerArtifact | DimensionGap]:
    """Dispatch every (dimension, url) in ``plan`` concurrently; total latency ~ slowest."""
    tasks = [
        _dispatch_or_gap(dimension, url, symbol, run_id, timeout_s, episodic_seed)
        for dimension, url in plan.items()
    ]
    return list(await asyncio.gather(*tasks))
```
- **P9의 실체**: 걸어야 할 통화 목록을 만들어 `asyncio.gather`로 전부 동시에 건다. 그게 전부다. 팀원 4명이 각자 5초 걸리는 일을 하면 총 소요는 ~5초(한 명씩 차례로 시키면 20초) — docstring의 *"total latency ~ slowest"*(전체 시간 ≈ 가장 느린 한 명의 시간). 이를 검증하는 테스트가 `test_fan_out_runs_in_parallel`(워커당 0.5초 대기, 총 1.0초 미만인지 확인)이다.
- `gather`에 `return_exceptions=True`(사고도 결과 목록에 끼워넣는 옵션)가 **없다**: 바로 아래층 `_dispatch_or_gap`이 이미 모든 사고를 메모로 바꿔놨으므로 gather까지 비상벨이 올라올 일이 없다. 사고 처리를 gather 옵션이 아니라 워커별 포장 함수에 두면, "시간 초과→메모" 번역에 담당 정보(dimension)를 쓸 수 있고, 결과 목록에 사고 객체가 섞여 들어가는 타입 오염도 없다.
- 입력이 `plan: dict[Dimension, str]`(담당→주소 표): 플래너가 고른 담당에게만 전화한다. 4명 고정이 아니라 계획표에 적힌 만큼만 — 플래너가 2명을 골랐으면 2명에게만 건다.

---

## 2. `planner.py` — 워커 발견과 장기 메모리 기반 계획

### 배경: 두 가지 결정이 만나는 곳

1. **AC#7 (data-driven registry)**: 팀원 명단을 팀장 코드 안에 박아두지(하드코딩하지) 않는다. 팀원들의 주소 목록(환경 설정값)만 주면, 각 주소에서 명함(Agent Card)을 받아와 "이 주소는 시세 담당이구나"를 **실행 시점에 알아낸다**. DESIGN.md: *"Keep the worker registry data-driven (env-var list of worker URLs) so adding a worker never edits `orchestrator/`"*. 팀원 추가 = 설정에 주소 한 줄 추가, 팀장 코드 수정 0줄.
2. **TENSION-B (장기 메모리 READ 트리거)**: 메모리가 "장식"이 되지 않으려면 실제로 행동을 바꿔야 한다(premise 5: *"Every memory layer needs a concrete trigger or it's decoration"*). 장기 메모리(팀장의 수첩 — 관심 코인 목록과 그간 배운 사실들)를 읽는 지점이 바로 플래너다 — 수첩 내용이 **이번에 어느 팀원을 투입할지**를 결정한다. TENSION-B는 이 읽기 시점을 M4가 아닌 M3(fan-out 단계)으로 앞당긴 결정이다: *"the read-trigger shapes orchestration, so it must be exercised in the core slice"*.

### 줄별 해설

```python
_DIMENSIONS: tuple[Dimension, ...] = ("market", "orderbook", "sentiment", "onchain")
```
- 이 코드는 "4개 분석 차원의 **공식 순서**는 이렇다"는 뜻. 순서 없는 집합이 아니라 순서 있는 튜플인 이유: 맨 마지막에 결과를 이 순서대로 정렬해 돌려주기 위해(아래 참조). 이름 앞의 `_`는 "이 파일 안에서만 쓰는 내부용"이라는 표시 — 이 순서는 플래너의 내부 사정이다.

```python
def _skill_dimension(card: AgentCard) -> Dimension | None:
    for dimension in _DIMENSIONS:
        if f"analyze:{dimension}" in card.skills:
            return dimension
    return None
```
- 이 코드는 "명함의 특기란(`skills`, 예: `["analyze:market"]`)을 보고 무슨 담당인지 알아낸다"는 뜻. `analyze:<차원이름>` 이라는 표기 규칙이 워커→팀장의 자기소개 프로토콜이다.
- `None` 반환(= "모르겠음"): 아는 특기가 하나도 없는 명함을 받은 경우. 에러를 내는 게 아니라 "그 워커는 무시"한다(아래 `discover`에서 명단에 안 올라감) — 정체 모를 워커가 섞여 있어도 시스템은 계속 굴러간다.

```python
async def _fetch_card(worker_url: str) -> AgentCard:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(f"{worker_url}/.well-known/agent.json")
    return AgentCard.model_validate(response.json())
```
- 이 코드는 "워커의 명함을 인터넷에서 받아온다"는 뜻. A2A 프로토콜의 약속된 관행으로, 명함은 항상 `/.well-known/agent.json`이라는 정해진 주소에 놓여 있다(contracts.md의 AgentCard 참조).
- 제한시간 10초가 dispatch의 30초와 별개로 고정값인 점: 명함 조회는 미리 만들어 둔 작은 파일을 건네주는 일이라 빨라야 정상이고, 설정으로 바꿀 수 있게 해달라는 요구도 없었다(불필요한 설정 옵션 만들기 금지).

```python
async def discover(worker_urls: list[str]) -> dict[Dimension, str]:
    cards = await asyncio.gather(*[_fetch_card(url) for url in worker_urls])
    registry: dict[Dimension, str] = {}
    for url, card in zip(worker_urls, cards, strict=True):
        dimension = _skill_dimension(card)
        if dimension is not None:
            registry[dimension] = url
    return registry
```
- 이 코드는 "모든 주소에서 명함을 동시에 받아와, 담당→주소 명단(registry)을 만든다"는 뜻. 명함 받기도 `asyncio.gather`로 동시 진행 — 1절 fan-out과 같은 패턴의 재등장이다.
- `zip(..., strict=True)`: 주소 목록과 명함 목록의 개수가 어긋나면(그럴 일이 없어야 하지만) 조용히 일부를 흘려버리는 대신 즉시 에러를 낸다. zip이라는 도구의 고전적 함정(짧은 쪽에 맞춰 말없이 잘라버림)을 한 단어로 차단.
- 돌려주는 값이 `dict[Dimension, str]`(담당→주소): 이후 모든 단계는 "주소"가 아니라 "담당"으로 생각한다. 주소는 실제 전화를 거는 직전에만 다시 등장한다.
- 주의: 명함 받기 실패(워커가 꺼져 있음)는 여기서 잡지 않는다 — gather가 비상벨을 그대로 올린다. dispatch와 달리 발견 단계의 부분 실패 흡수는 구현돼 있지 않다(현 단계 범위 밖).

```python
def plan_dimensions(
    symbol: str, registry: dict[Dimension, str], longterm: LongTermMemory
) -> list[Dimension]:
    """Long-term READ: market always; others iff watchlisted or named by a stored fact."""
    chosen: set[Dimension] = set()
    if "market" in registry:
        chosen.add("market")
```
- **계획 규칙 1**: 시세(market)는 무조건 분석한다(명단에 그 담당이 있는 한). "어떤 코인이든 시세는 본다"는 기본선이다. 이 덕분에 수첩이 텅 빈 첫 실행에도 보고서가 빈손이 아니다.
- 이 함수에 `async`가 없는(동기 함수인) 점: 명함 받기(통신)와 계획 세우기(머릿속 계산만 하는 순수 로직)를 분리했다. 통신이 전혀 없는 순수 함수라, 테스트(`test_planner_longterm_read`)는 가짜 수첩만 끼워 넣으면 끝난다.

```python
    watched = symbol in longterm.watchlist()
    fact_tokens = set(re.findall(r"[a-z0-9]+", " ".join(longterm.facts(symbol)).lower()))
```
- **여기가 장기 메모리 읽기(READ 트리거)의 실제 지점.** `watchlist()`(관심 코인 목록)와 `facts(symbol)`(그 코인에 대해 배운 사실들) — contracts.md의 `LongTermMemory` 규격에서 "읽기: 플래너"라고 주석된 바로 그 두 메서드가 여기서 호출된다.
- `fact_tokens`: 쌓인 사실 문장들을 소문자로 바꾸고 → 단어 단위(영숫자 토큰)로 쪼개 단어 집합으로 만든다. **리뷰 O2의 수정 결과**다. 원래는 "사실 문장 어딘가에 그 글자가 들어 있나"(부분 문자열 매칭)였는데, 리뷰가 망가지는 시나리오를 짚었다: 사실 문장에 "market", "chain" 같은 단어가 우연히 섞이면 거의 모든 차원이 항상 선택돼버려, "장기 메모리가 투입 인원을 **의미 있게** 좁힌다"는 TENSION-B의 시연이 무너진다. 권장 해법 (b) *"매칭을 부분문자열→정확한 토큰 매칭으로 교체"* 가 채택됐다. 이제 사실 문장에 정확히 `onchain`이라는 **단어**가 있어야 onchain 담당이 선택된다("blockchain" 안에 chain이 들어 있어도 단어가 다르므로 매칭 안 됨).

```python
    for dimension in registry:
        if dimension == "market":
            continue
        if watched or dimension in fact_tokens:
            chosen.add(dimension)
    return [d for d in _DIMENSIONS if d in chosen]
```
- **계획 규칙 2**: 시세 외 담당은 (a) 그 코인이 관심 목록에 있거나, (b) 저장된 사실이 그 담당 이름을 단어로 언급할 때만 투입한다. 즉 "관심 코인이면 풀 분석, 아니면 시세만 + 과거에 배워서 필요하다고 적어둔 차원만".
- 마지막 줄의 정렬 관용구: `chosen`은 집합이라 순서가 매번 다를 수 있으므로, 공식 순서표 `_DIMENSIONS`로 걸러서 **항상 같은 순서의 목록**으로 바꾼다. 출력 순서가 일정해야 테스트와 로그가 흔들리지 않는다.

---

## 3. `synthesize.py` — 합성: 커버리지를 숨기지 않는 병합

### 배경: TENSION-C — "1/4 성공한 실행은 눈에 보이게 partial이어야 한다"

DESIGN.md: *"The synthesis report carries explicit per-dimension coverage (`dimensions_ok`, `dimensions_unavailable`); the CLI surfaces it; a test asserts a 1-of-4 run is visibly marked partial."* 합성기의 일은 단순히 풀로 이어 붙이는 게 아니라 **회계**다 — 무엇이 들어왔고 무엇이 빠졌는지를 빠짐없이 장부에 남긴다. 4명 중 1명만 보고했다면, 최종 보고서가 그 사실을 대놓고 말해야 한다.

fan-out에서 도착하는 결과는 **세 종류**다(docstring이 명시):
1. `status="ok"`인 `WorkerArtifact` — 팀원이 일을 잘 끝낸 요약 보고 → 보고서에 기여
2. `status="failed"`인 `WorkerArtifact` — 팀원과 연락은 됐지만 팀원 스스로 "일을 못 했다"고 보고한 경우(예: 참고하던 데이터 창고 MCP 서버가 다운) → 결손 메모(gap)로 번역
3. `DimensionGap` — 팀원에게 아예 연락이 안 닿은 경우(시간 초과/접속 불가)

2와 3의 구분이 미묘하지만 중요하다: "팀원이 살아서 '제 자료 출처가 죽었어요'라고 말한 것"과 "팀원이 아예 응답이 없는 것"은 다른 종류의 실패다. contracts.md에서 본 "실패해도 artifact는 반환된다"(워커의 failed artifact)가 여기서 gap과 합류한다.

### 줄별 해설

```python
def _gaps(results: list[WorkerArtifact | DimensionGap]) -> list[DimensionGap]:
    gaps = [r for r in results if isinstance(r, DimensionGap)]
    for r in results:
        if isinstance(r, WorkerArtifact) and r.status == "failed":
            reason = r.key_points[0] if r.key_points else "worker reported failure"
            gaps.append(DimensionGap(dimension=r.dimension, reason=reason))
    return gaps
```
- 이 코드는 "결손 목록을 모은다"는 뜻: 종류 3(연락 두절 메모)은 그대로 수집하고, 종류 2(자가 보고 실패)는 결손 메모로 **번역**한다. 실패한 팀원 보고의 첫 번째 요점(key_point)을 실패 이유로 채택한다 — 워커가 실패하면 "왜 실패했는지"를 key_points 첫 줄에 적는다는 암묵적 약속이 있다. 비어 있으면 기본 문구를 쓴다.
- `isinstance` 분기(= "이게 어느 종류인지 확인"): 두 종류가 섞인 목록을 다루는 정직한 방법이다. 둘 다 Pydantic 모델이라 실행 중에도 구분이 명확하다.

```python
def _status(
    ok: list[WorkerArtifact], gaps: list[DimensionGap]
) -> Literal["ok", "partial", "failed"]:
    if not ok:
        return "failed"
    return "partial" if gaps else "ok"
```
- 최종 보고서의 3단계 상태를 정하는 로직 전체가 단 두 줄: 성공 0건이면 failed(A3의 zero-artifact 경로 — CLI가 이를 받아 "비정상 종료" 신호로 변환), 결손이 하나라도 있으면 partial(부분 성공), 아니면 ok. contracts.md에서 본 "워커는 2단계 상태, 합성은 3단계 상태"의 세 번째 값(`partial`)이 태어나는 곳이다.

```python
def synthesize(symbol: str, results: list[WorkerArtifact | DimensionGap]) -> SynthesisReport:
    ok = [r for r in results if isinstance(r, WorkerArtifact) and r.status == "ok"]
    gaps = _gaps(results)
    headline = f"{symbol}: {len(ok)}/{len(ok) + len(gaps)} dimensions covered"
```
- 보고서 제목(headline)이 곧 커버리지 선언: "BTC: 3/4 dimensions covered"(BTC: 4개 항목 중 3개 분석됨). 보고서 첫 줄부터 부분 실패가 보인다 — TENSION-C의 "눈에 보이게(visibly marked)"를 제목 수준에서 실천.
- `len(ok) + len(gaps)`가 분모인 이유: 모든 결과는 성공 아니면 결손으로 정확히 한 번씩 분류되므로, 둘을 합치면 계획했던 항목 수와 같다. 계획표를 따로 넘겨받지 않아도 장부가 맞아떨어진다.

```python
    return SynthesisReport(
        symbol=symbol,
        status=_status(ok, gaps),
        headline=headline[:200],
        key_points=[point for artifact in ok for point in artifact.key_points][:10],
        evidence=[item for artifact in ok for item in artifact.evidence],
        dimensions_ok=[artifact.dimension for artifact in ok],
        dimensions_unavailable=gaps,
    )
```
- `headline[:200]`: 제목을 200자에서 잘라내는 안전장치. 보고서 양식의 상한이 200자인데, 넘으면 양식 검사(Pydantic)에 걸려 보고서 생성 자체가 죽으므로 미리 자른다. 현재 형식상 넘을 일은 없지만 만약을 위한 방어.
- `key_points` 줄 + `[:10]`: 성공한 보고들의 요점을 담당 순서대로 이어 붙이고, 최대 10개에서 자른다(contracts.md: 워커당 5개 × 합성 후 10개). **현재는 AI가 다시 써주는 게 아니라 기계적으로 이어 붙이기만 한다** — 진짜 "요점 재서술"은 Approach C(critic/compressor)의 영역으로 의도적으로 미뤄져 있다.
- `evidence`(근거 자료 목록)에는 자르기가 **없다**: `SynthesisReport.evidence` 양식에 상한이 없어서 통과는 되지만, 리뷰 03이 이를 열린 항목으로 남겼다 — 수정 Todolist의 미체크 항목 *"C1 연계: evidence concat에 `[:N]` 방어 슬라이스 도입 여부 결정(증거 폭주 방지)"*. 알려진 미결정 사항이다.
- `dimensions_ok` + `dimensions_unavailable=gaps`: TENSION-C가 요구한 두 칸 — "된 항목 목록"과 "안 된 항목 목록" — 을 채우는 곳. 이 함수는 들어온 결과 전부를 둘 중 한 칸으로 보내므로 "두 칸을 합치면 계획 전체"라는 장부 원칙이 구조적으로 성립한다.
- 순수 함수(async 아님, 통신·저장 없음)인 점도 의도: 부분 성공/전원 실패 테스트(`test_partial`, `test_zero_artifact`)가 가짜 보고 목록만 넣으면 돌아간다.

---

## 4. `app.py` — 그래프 조립과 실행 수명주기

### 배경: LangGraph는 여기서 무슨 역할인가

P9에서 봤듯 일 나눠주기(fan-out)는 LangGraph 바깥(`asyncio.gather`)에서 일어난다. 그럼 LangGraph는 왜 쓰나? — **단계 사이의 서류철 운반과 작업 순서도의 명시**다. 계획 단계의 산출물(plan)이 분배 단계의 입력이 되고, 분배의 산출물(results)이 합성의 입력이 되는 흐름을, `OrchestratorState`라는 서류철 + 단계(노드) 순서도로 표현한다. 각 단계는 자기가 새로 끼울 서류만 돌려주고, LangGraph가 서류철에 합쳐 넣는다.

### 줄별 해설

```python
class OrchestratorState(TypedDict, total=False):
    symbol: str
    run_id: str
    worker_urls: list[str]
    longterm: LongTermMemory
    timeout_s: float
    episodic_seed: dict[str, str] | None
    plan: dict[Dimension, str]
    results: list[WorkerArtifact | DimensionGap]
    report: SynthesisReport
```
- **이 서류철 정의(TypedDict)가 격리(A2)의 증명서다.** 팀장이 실행 중에 들고 있을 수 있는 **모든 것**의 목록인데, 워커의 원자료가 들어갈 칸이 아예 존재하지 않는다. `results` 칸에는 `WorkerArtifact | DimensionGap` — 요약 보고 아니면 결손 메모만. 격리 테스트(`test_isolation`)가 "시세 1000행을 먹여도 팀장 서류철에 원자료 0개"를 확인할 때 검사하는 대상이 바로 이 서류철이다.
- 칸은 3그룹: 입력(symbol~episodic_seed), 계획 단계 산출물(plan), 분배 단계 산출물(results), 합성 단계 산출물(report). 순서도를 따라갈수록 서류철이 점점 채워진다.
- `total=False`(= "모든 칸은 비어 있어도 됨"): 시작 시점엔 plan/results/report가 아직 없기 때문이다. LangGraph 서류철의 "점진적 채움" 패턴.
- `longterm: LongTermMemory`(팀장의 수첩)가 서류철에 들어 있는 점: 데이터베이스 연결 같은 도구를 서류철에 끼워 운반한다. 각 단계가 전역 변수가 아니라 서류철에서 도구를 꺼내 쓰므로, 테스트에서 가짜 수첩으로 바꿔치기가 자연스럽다. (Protocol 타입이라 규격만 맞으면 어떤 구현이든 OK — contracts.md 5절.)

```python
async def _plan(state: OrchestratorState) -> dict[str, Any]:
    registry = await discover(state["worker_urls"])
    chosen = plan_dimensions(state["symbol"], registry, state["longterm"])
    return {"plan": {dimension: registry[dimension] for dimension in chosen}}
```
- 이 코드는 "계획 단계 = 명함 수집(통신) + 인원 선발(순수 계산)을 합친 것"이라는 뜻. 돌려주는 건 새로 끼울 서류 한 장(`plan`)만 담은 dict — LangGraph 단계의 "내가 바꾼 것만 반환" 규약.
- 마지막 줄: 선발된 담당만 골라 `{담당: 주소}` 표로 좁힌다. 분배 단계는 선발 안 된 워커의 존재 자체를 모른다.

```python
async def _dispatch(state: OrchestratorState) -> dict[str, Any]:
    results = await fan_out(
        state["plan"], state["symbol"], state["run_id"],
        state.get("timeout_s", 30.0), state.get("episodic_seed"),
    )
    return {"results": results}
```
- fan_out을 불러주는 얇은 연결 코드. `state.get("timeout_s", 30.0)`: 서류철의 모든 칸이 비어 있을 수 있으므로(`total=False`), 없을 수도 있는 칸은 "없으면 기본값"으로 꺼내는 `.get`을 쓴다. 반드시 있어야 하는 칸(`state["plan"]`)과 꺼내는 방식이 다른 것 자체가 문서 역할을 한다.

```python
def _synthesize(state: OrchestratorState) -> dict[str, Any]:
    return {"report": synthesize(state["symbol"], state["results"])}
```
- 유일하게 `async`가 붙지 않은 단계 — synthesize가 기다릴 통신이 전혀 없는 순수 계산이기 때문. LangGraph는 두 종류의 단계를 섞어 받아준다.

```python
def build_orchestrator() -> Any:
    graph = StateGraph(OrchestratorState)
    graph.add_node("plan", _plan)
    graph.add_node("dispatch", _dispatch)
    graph.add_node("synthesize", _synthesize)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "dispatch")
    graph.add_edge("dispatch", "synthesize")
    graph.add_edge("synthesize", END)
    return graph.compile()
```
- 순서도 정의의 전부다: 시작→계획→분배→합성→끝, 갈림길 0개. "LangGraph니까 복잡한 그래프를 그려야지"가 아니라, 필요한 만큼만 — 일직선이면 일직선으로 그린다.
- 돌려주는 타입이 `Any`(= "타입 표기 생략"): LangGraph가 만들어내는 결과물의 정식 타입 이름이 너무 길고 복잡해서 실용적으로 생략했다. 외부 라이브러리와 만나는 경계에서 흔한 타협이다.

```python
def _episodic_seed(prior: RunRecord | None) -> dict[str, str] | None:
    """A compact reference to the last run, passed to workers via ``TaskParams.episodic_seed``."""
    if prior is None:
        return None
    return {"prior_run_id": prior.run_id, "prior_headline": prior.report.headline}
```
- 이 코드는 "지난 실행 기록(`RunRecord`, 보고서 전체 포함)에서 **딱 두 조각**(실행 ID, 보고서 제목)만 추려 쪽지(seed)로 만든다"는 뜻. 왜 지난 보고서를 통째로 안 넘기나? — "요약본만 주고받는다"는 증류 원칙은 메모리→워커 방향에도 적용된다. 지난 보고서 전문이 팀원 4명의 업무 지시문에 다 들어가면 분량만 부풀고, 팀원에게 필요한 건 "지난번엔 이런 결론이었다"는 한 줄 참조면 충분하다.

```python
async def run_orchestrator(
    symbol: str, run_id: str, worker_urls: list[str],
    longterm: LongTermMemory, timeout_s: float = 30.0,
    episodic: EpisodicMemory | None = None,
) -> SynthesisReport:
    # Run start: read the last run for this symbol and seed it into the worker dispatch.
    seed = _episodic_seed(episodic.last_for(symbol)) if episodic is not None else None
```
- 시스템 전체의 정문(진입점). **에피소드 메모리(지난 회의록 보관함) 읽기가 첫 줄**이다 — DESIGN.md의 메모리 트리거 표: *"episodic: Read trigger = run start retrieves the most recent run row keyed by symbol"*. contracts.md의 `EpisodicMemory.last_for` 주석("읽기: 실행 시작 시")이 코드로 실현되는 지점.
- `episodic`이 선택 사항(Optional)인 이유: 회의록 없이도 돌 수 있어야 한다(테스트, 초기 마일스톤 호환). 반면 `longterm`(수첩)은 필수 — 플래너가 수첩 없이는 계획을 못 세우기 때문. 일부러 둔 비대칭이다.

```python
    final = await build_orchestrator().ainvoke(
        {
            "symbol": symbol, "run_id": run_id, "worker_urls": worker_urls,
            "longterm": longterm, "timeout_s": timeout_s, "episodic_seed": seed,
        }
    )
    report = cast(SynthesisReport, final["report"])
```
- 이 코드는 "초기 서류철을 넣고 순서도를 끝까지 돌린다"는 뜻(`ainvoke` = 비동기 실행). 호출할 때마다 순서도를 새로 조립한다 — 재사용 캐싱은 실제 측정으로 필요가 확인되기 전까지 안 한다.
- `cast(...)`: 실행 결과가 느슨한 dict 형태라, 타입 검사기(mypy)에게 "이 칸은 SynthesisReport 맞아"라고 알려주는 표기다. 실행 중 검사가 아니라 주석에 가깝다(합성 단계가 그 칸에 보고서를 넣었음을 우리가 알기에 안전).

```python
    # Run end: store this run (episodic) and append what it learned (long-term).
    if episodic is not None:
        episodic.put(RunRecord(run_id=run_id, symbol=symbol, ts=int(time.time()), report=report))
    longterm.add_facts(symbol, report.key_points)
    return report
```
- **두 메모리에 쓰기(WRITE 트리거)가 마지막 두 줄**이다 — *"write trigger = run end stores this run"*(에피소드: 이번 실행을 회의록으로 보관), *"write trigger = run end appends newly learned facts"*(장기: 새로 배운 사실을 수첩에 추가). 읽기는 시작에, 쓰기는 끝에: 메모리를 만지는 지점이 실행의 양 끝에만 있고 순서도 내부엔 없다(작업 중 임시 기억은 워커 쪽 checkpointer 소관, A4: 팀장만이 에피소드/장기 DB를 소유).
- `add_facts(symbol, report.key_points)`: 이 줄은 리뷰 **O2**가 지적한 지점이다 — 매 실행의 요점을 무조건 수첩에 적으면 같은 내용이 무한정 중복으로 쌓여 수첩이 잡동사니가 된다(신호 퇴화). 리뷰의 처방은 (b) 플래너의 단어 단위 매칭(planner.py에 반영 완료) + (c) `add_facts` 쪽 중복 제거와 개수 상한(메모리 구현부 소관)이었고, Todolist상 둘 다 체크돼 있다. 호출하는 이 줄 자체는 그대로다 — 방어 장치는 수첩 구현과 플래너 매칭에 두고, 수명주기 코드는 단순하게 유지.

---

## 5. 관통하는 설계 원칙 요약

1. **프레임워크 기능보다 경계가 우선 (P9)** — LangGraph에 `Send`라는 분배 기능이 있어도 안 쓴다. `Send`는 건물(프로세스) 경계를 못 넘고, 그걸 쓰는 순간 "별도 프로세스 + 실제 통신 규약"이라는 아키텍처가 조용히 한 사무실 시뮬레이션으로 퇴화한다. 일 나눠주기는 평범한 `asyncio.gather` 인터넷 동시 호출이다.
2. **실패를 값으로 번역하고, 번역 지점을 한 곳에 (A3)** — `dispatch_one`은 비상벨(예외)을 울리고(낮은 층), `_dispatch_or_gap`이 그걸 "못 받았음" 메모(`DimensionGap`)로 번역하며(중간층), 그 위층에는 비상벨이 존재하지 않는다. gather가 전체 중단될 가능성을 워커별 포장 함수에서 원천 차단.
3. **회계는 빠짐없이, 커버리지는 첫 줄부터 (TENSION-C)** — synthesize는 모든 결과를 "성공" 아니면 "결손"으로 정확히 한 번씩 분류한다. "3/4 dimensions covered"가 보고서 제목이고, `dimensions_ok`/`dimensions_unavailable` 두 칸의 합은 항상 계획 전체와 같다.
4. **메모리는 트리거가 있어야 진짜다 (TENSION-B, premise 5)** — 수첩(장기 메모리) 읽기는 플래너에서 투입 인원을 실제로 바꾸고, 회의록(에피소드) 읽기는 실행 시작에 쪽지(seed)가 되며, 두 쓰기는 실행 끝에 있다. 읽고 쓰는 지점을 코드에서 손가락으로 짚을 수 있다.
5. **상태 스키마가 격리의 증명서 (A2)** — 팀장 서류철(`OrchestratorState`)에는 원자료가 들어갈 칸이 타입상 존재하지 않는다. 격리는 "조심하자"는 다짐이 아니라 TypedDict + 프로세스(건물) 경계 + isolation 테스트로 강제된다.
6. **통신(I/O)과 순수 계산의 분리** — `discover`(통신) vs `plan_dimensions`(순수), `fan_out`(통신) vs `synthesize`(순수). 통신이 없는 순수 함수들 덕에 partial/zero/planner 테스트가 네트워크 없이 돈다.
7. **리뷰가 메커니즘을 조였다 (O1, O2)** — "타임아웃이 있다"에서 "워커당 손목시계 마감 하나가 확실히 보장된다"(`asyncio.wait_for`)로, "사실 매칭이 된다"에서 "우연히 섞인 글자 조각에 오염되지 않는다"(단어 집합 매칭)로. 둘 다 일단 동작하던 코드의 **망가지는 경로**를 리뷰가 찾아 막은 사례 — 테스트가 통과하는 것과 메커니즘이 견고한 것은 다르다.
