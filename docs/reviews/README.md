# 코드 리뷰 — crypto_deep_research (M0–M5 vertical slice)

> 작성: 2026-06-09 · 대상 커밋 `e2eb506` "feat: M0-M5 vertical slice"
> 기준 spec: `docs/specs/M0-M5-vertical-slice-epic.md` + `docs/specs/phases/M*.md` + `docs/DESIGN.md`
> 게이트 현황(status 문서): pytest 31 passed / 2 skipped, ruff·mypy clean

기능 컴포넌트별 코드 리뷰. 각 문서는 4관점(① spec 적합성 ② 정확성/버그 ③ 보안 ④ 테스트 커버리지)으로
대상 코드를 초기 spec과 대조하고, 발견 항목을 근거(file:line)·해결방안과 함께 기록한다.

## 리뷰 문서

| 문서 | 대상 | milestone |
|------|------|-----------|
| [01-contracts.md](./01-contracts.md) | `contracts/` (artifact, report, a2a, mcp_tools, memory) | M0 |
| [02-mcp-server.md](./02-mcp-server.md) | `mcp_server/` (server, sources/base·fixture·coingecko) | M1, M5 |
| [03-orchestrator.md](./03-orchestrator.md) | `orchestrator/` (app, planner, dispatch, synthesize) | M3 |
| [04-workers.md](./04-workers.md) | `workers/` (base + market/orderbook/sentiment/onchain) | M1–M3 |
| [05-memory.md](./05-memory.md) | `memory/` (working, episodic, longterm) | M4 |
| [06-wiring-cli-packaging.md](./06-wiring-cli-packaging.md) | `wiring.py`, `__main__.py`, `serve_worker.py`, Docker | M0, M5 |

## 종합 판정

전체적으로 **M0–M5 spec과 locked decisions(A1–A4, P9, C5/C6, TENSION-B/C)에 충실하게 구현**되어 있다.
계약·격리·분산·커버리지의 핵심 데모(특히 isolation flagship, partial/zero/timeout, 데이터 주도 registry)는
실제로 동작하고 테스트로 증명된다. High 심각도(크래시·키 유출·spec 정면 위반)는 없다.

다만 status 문서가 "honest"하게 밝힌 2개 gap이 코드로 확정되며, 그 외 일부 spec 데모가 **테스트 스텁으로만**
증명되고 라이브 경로에서는 비어 있다. 가장 주목할 4건(Medium):

- **W1** episodic_seed가 worker까지 전달되지만 `analyze(symbol, mcp_url)`에서 폐기 → 라이브 worker는 직전 run을 참조하지 않음 (M4 AC#1은 테스트 스텁으로만 충족).
- **W2** working memory checkpointer가 라이브 경로에 미연결 (테스트에서만 호출).
- **W3** orderbook/sentiment/onchain worker 직접 테스트 0건 — 결정론 산술(spread/imbalance/netflow)이 미검증.
- **O2** `add_facts(symbol, report.key_points)`가 매 run 모든 key_point를 facts로 무제한 적재 + planner가 부분문자열 매칭 → 누적될수록 long-term READ 신호가 사실상 전 dimension 매칭으로 퇴화 (TENSION-B 데모 약화).

## Findings 전체 (severity 순)

| ID | 컴포넌트 | 관점 | 심각도 | 한 줄 요약 |
|----|----------|------|--------|-----------|
| W1 | workers | spec 적합성 | **Med** | `base.py:150` analyze가 `episodic_seed`·`run_id` 폐기 (status gap #2) |
| W2 | workers/memory | spec 적합성 | **Med** | `run_worker` checkpointer 라이브 미주입 (status gap #1) |
| W3 | workers | 커버리지 | **Med** | orderbook/sentiment/onchain 직접 테스트 없음 |
| O2 | orchestrator | 정확성 | **Med** | facts 무제한 적재 + 부분문자열 planner 매칭으로 READ 신호 퇴화 |
| W4 | workers | 보안 | Low | sentiment가 외부 헤드라인을 LLM 프롬프트에 직접 주입(injection 표면) |
| O1 | orchestrator | spec 문구 | Low | A3/docstring "via asyncio.gather" vs 실제 httpx per-op 타임아웃 |
| C2 | contracts | 정합성 | Low | `WorkingMemory.note/read` protocol 구현체 부재(orphan) |
| C1 | contracts | 정확성 | Low | `SynthesisReport.evidence` 캡 없음(최대 40개 concat) — spec엔 부합 |
| W6 | workers | 정확성 | Low | orderbook `_work` 0-depth/0-mid 가드 없음(빈 호가창 시 모호한 gap) |
| W5 | workers | 효율 | Low | `llm_distill` LLM 2회 호출(reason→structure) |
| S2 | mcp-server | 정확성 | Low | CoinGecko `volume=0.0` 하드코딩(엔드포인트 한계, 문서화됨) |
| S3 | mcp-server | 견고성 | Low | `_SYMBOL_TO_ID`는 BTC/ETH만; 그 외 심볼 404/fixture 부재 |
| WC1 | wiring/cli | 커버리지 | Low | `wiring.py`·`parse_symbol`·`serve_worker` 미테스트 (M0 AC#5 무검증) |
| WC2 | cli | 견고성 | Low | `parse_symbol("analyze bitcoin")` → "BITCOIN" (매핑/fixture 없음) |
| WC3 | packaging | 보안 | Low | A2A/MCP 엔드포인트 무인증(0.0.0.0 bind) — epic상 auth는 out of scope |

> Severity 기준: **Med** = 핵심 개념 데모가 라이브에서 불완전하거나 검증 안 됨(크래시는 아님).
> Low = 견고성·문구·효율·범위 밖 항목. High(크래시/키 유출/spec 정면 위반)는 없음.

## 착수 가이드 (다음 세션 에이전트용 — 콜드 스타트)

> 이 섹션 + 해당 기능 문서만 읽으면 곧바로 수정에 착수할 수 있도록 정리했다.
> 코드 수정은 아직 **미착수**(deferred). 아래 순서대로 진행하면 된다.

### 0. 사전 준비 (환경)
- **`uv`는 PATH에 없음** → 항상 `& "$env:USERPROFILE\.local\bin\uv.exe"`로 실행 (shell: PowerShell).
- 이 머신은 TLS 가로채기(MITM) → `pyproject.toml`에 `[tool.uv] system-certs = true` 이미 설정됨. 추가 조치 불필요.
- `ANTHROPIC_API_KEY`는 **불필요**(미설정 시 T7/T8 2건만 skip). 결정론 수정·테스트는 전부 스텁(T7b)으로 가능.
- 게이트(매 수정 후):
  ```powershell
  & "$env:USERPROFILE\.local\bin\uv.exe" run ruff check .
  & "$env:USERPROFILE\.local\bin\uv.exe" run mypy .
  & "$env:USERPROFILE\.local\bin\uv.exe" run pytest -q
  ```
- `tests/test_fanout.py::test_fan_out_runs_in_parallel`은 타이밍 의존 → 부하 시 flake. 회귀로 단정하기 전 **단독 재실행**.

### 1. 수정 대상 (코드 변경) — 권장 실행 순서
의존성과 "회귀 안전망 먼저" 원칙에 따른 순서. 각 항목의 상세(file:line·해결방안·verify)는 해당 기능 문서에 있다.

| 순서 | ID | 작업 | 주관 문서 | 비고 |
|------|----|------|-----------|------|
| 1 | **W3** | orderbook/onchain `_work` 산술 + sentiment MCP-down + 3 Agent Card 테스트 추가 | [04](./04-workers.md) | **먼저** — 이후 worker 수정의 회귀 가드 |
| 2 | **W6** | orderbook `_work` 0-depth/0-mid 가드 → failed 반환 | [04](./04-workers.md) | W3 테스트에 빈 호가창 케이스 포함 |
| 3 | **W4** | sentiment 프롬프트에 untrusted-data 구분자/지시(injection 방어) | [04](./04-workers.md) | 스텁 LLM 테스트로 데이터-취급 단정 |
| 4 | **W1** | `analyze`/`run_worker`/`analyze_route`에 `episodic_seed` 스레딩 + LLM `_work` 반영 | [04](./04-workers.md) | status gap #2 |
| 5 | **W2** | 라이브 경로에 worker별 checkpointer 주입(`working_db_path`/`worker_checkpointer`) | [04](./04-workers.md)·[05](./05-memory.md) | status gap #1, MEMORY_DIR env |
| 6 | **O2** | planner 부분문자열→토큰/태그 매칭 교체 + `add_facts` dedup/상한 | [03](./03-orchestrator.md)·[05](./05-memory.md) | TENSION-B 신호 복원 |
| 7 | **O1** | `dispatch_one`을 `asyncio.wait_for(timeout_s)`로 감싸 단일 wall-clock 마감 + docstring 일치 | [03](./03-orchestrator.md) | `test_timeout` 통과 유지 |
| 8 | **WC1** | `tests/test_wiring.py` — 필수 env 누락→RuntimeError, 기본 timeout, `parse_symbol` | [06](./06-wiring-cli-packaging.md) | M0 AC#5 실검증 |
| 9 | **C2** | `WorkingMemory.note/read` protocol에 "checkpointer로 대체" 주석 | [01](./01-contracts.md) | 동작 무변경 |

각 수정은 surgical(요청 직접 연결분만), 기존 스타일·30줄 규칙·typed schema·T7/T7b 스텁 규칙 준수.

### 2. 건드리지 말 것 (문서화만 — 코드 변경 X)
- **C1** `SynthesisReport.evidence` 무캡 — epic normative 스케치(line 154)도 무캡이라 **현재 코드가 spec 부합**. 변경 시 spec 이탈.
- **S2/S3** CoinGecko `volume=0.0`·BTC/ETH 한정 — "BTC 단일 슬라이스" DoD 내 의도된 한계.
- **WC2** `parse_symbol`이 "bitcoin"→"BITCOIN" — 위와 동일(BTC/ETH만 지원).
- **WC3** A2A/MCP 무인증 `0.0.0.0` bind — epic "Auth out of scope"(신뢰 네트워크 전제).
- **W5** `llm_distill` 2-call — distillation 가시화 **학습 의도일 수 있어, 변경 전 사용자/의도 확인 필요**(임의 병합 금지).
- **Mem4** episodic·longterm 별도 connection 2개 — 단일 프로세스라 무해(정보성).

### 3. 완료 정의
1~9 적용 + 신규 테스트 통과, ruff/mypy clean, pytest는 기존 31 + 신규(worker 3종·wiring·dedup 등) 통과
(키 미설정 시 T7/T8 2건만 skip). `docs/status/current_status.md`의 "Known gaps" 2건이 해소로 갱신되면 마감.

## 범위 밖

`TODOS.md`의 deferred 항목(Approach C, 공식 a2a SDK, JSON-Schema 계약, in-proc `Send`)과
auth/멀티유저/Binance·Upbit 라이브는 epic "Out of Scope"이므로 "정상 미구현"으로만 기록하고 수정하지 않는다.
