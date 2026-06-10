# Review 03 — orchestrator

## 대상 파일
- `crypto_deep_research/orchestrator/app.py` — LangGraph plan→dispatch→synthesize + run lifecycle
- `crypto_deep_research/orchestrator/planner.py` — `discover`(Agent Card registry) + `plan_dimensions`(long-term READ)
- `crypto_deep_research/orchestrator/dispatch.py` — `dispatch_one`/`fan_out`(asyncio.gather, P9) + per-worker gap
- `crypto_deep_research/orchestrator/synthesize.py` — artifact merge → `SynthesisReport`(TENSION-C)

## 대조 spec
- `phases/M3.md` AC#1–#7, locked decisions P9(gather, not Send), A2(isolation), A3(timeout/zero), TENSION-B(long-term READ), TENSION-C(coverage)

## 리뷰 체크리스트

### ① Spec 적합성
- [x] M3 AC#1 4-worker 병렬 fan-out via `asyncio.gather` over A2A (dispatch.py:66–70) — `test_fanout::test_fan_out_runs_in_parallel`(총지연≈최슬로워)
- [x] P9 준수: `Send` 미사용, A2A HTTP gather (dispatch.py docstring + 구현)
- [x] M3 AC#2 isolation: 오케스트레이터 state는 `WorkerArtifact|DimensionGap`만 보유, raw OHLCV 없음 (app.py:23–32) — `test_isolation`
- [x] M3 AC#3 partial: 1 실패 → `status="partial"` + `dimensions_unavailable` (synthesize.py:26–31) — `test_partial`
- [x] M3 AC#4 zero: 0 성공 → `status="failed"`, CLI 비정상 종료 (synthesize.py:29–30 + `__main__.exit_code`) — `test_zero_artifact`
- [x] M3 AC#5 timeout: 느린 worker → gap, gather 반환 (dispatch.py:52–53) — `test_timeout` (**메커니즘은 O1 참조**)
- [x] M3 AC#6 long-term READ: `plan_dimensions`가 `watchlist()`/`facts()` 읽어 worker set 결정 (planner.py:45–59) — `test_planner_longterm_read`
- [x] M3 AC#7 data-driven registry: `discover`가 Agent Card로 registry 구성 → worker 추가 시 orchestrator 무변경 (planner.py:34–42)

### ② 정확성/버그
- [x] `_dispatch_or_gap`이 TimeoutException/일반 예외를 gap으로 흡수 — gather가 raise로 중단되지 않음 (dispatch.py:42–55)
- [x] `synthesize`의 3-결과종류 처리(ok/failed-artifact/gap) 명확 (synthesize.py:17–31)
- [⚠️] A3·docstring "per-worker timeout **via asyncio.gather**" ↔ 실제 `httpx.AsyncClient(timeout=timeout_s)` per-op 타임아웃 (dispatch.py:33) → **O1**
- [⚠️] `run_orchestrator`가 매 run `longterm.add_facts(symbol, report.key_points)` 무제한 적재(app.py:99) + `plan_dimensions`의 `dimension in facts_text` 부분문자열 매칭(planner.py:57) → 신호 퇴화 → **O2**

### ③ 보안
- [x] orchestrator는 worker의 distilled artifact만 수신 — raw context·prompt 미수신(격리)
- [x] `discover`/`dispatch`는 신뢰된 내부 worker URL(env wiring)만 호출
- [△] worker 응답을 `JsonRpcResponse.model_validate`로 검증 후 사용(dispatch.py:35) — 악의적 worker 응답도 스키마 경계 통과분만 수용(양호)

### ④ 테스트 커버리지
- [x] fanout/timeout/partial/zero/isolation/planner-READ 모두 테스트 존재(M3 5종 + isolation)
- [△] `test_fanout::test_fan_out_runs_in_parallel`는 타이밍 의존(0.5s/worker, total<1.0s) — 부하 시 flake 가능(기지 메모: flaky-fanout-timing-test). 회귀 단정 전 단독 재실행 권장

## Findings

| ID | 관점 | 심각도 | 근거 | 해결방안 |
|----|------|--------|------|----------|
| **O2** | 정확성/견고성 | **Med** | `app.py:99` `longterm.add_facts(symbol, report.key_points)` — 매 성공 run마다 key_point(최대 10개) 무제한·무중복 적재. `planner.py:57` `if watched or dimension in facts_text` — 누적 facts를 lowercase join 후 dimension 이름 **부분문자열** 매칭. 결과: 몇 run 후 facts에 "market/order/chain/sentiment" 류 단어가 섞이면 거의 모든 dimension이 항상 선택 → TENSION-B(long-term READ가 worker set을 의미 있게 좁힌다)의 데모가 퇴화. M4 AC#2는 기술적으로 충족하나 메커니즘이 취약 | (a) 적재를 **타깃화**: 막연한 key_point 대신 dimension 태그가 붙은 구조적 fact만 저장(예: `add_facts`에 dimension 명시), (b) `plan_dimensions` 매칭을 부분문자열→정확한 토큰/태그 매칭으로 교체, (c) facts dedup 또는 상한. **권장: (b)+(c)** — planner 매칭을 명시 토큰 집합으로 바꾸고 add_facts에 dedup. 테스트 `test_longterm_affects_plan`/`test_planner_longterm_read` 의미 유지 확인 |
| **O1** | spec 문구/메커니즘 | Low | `dispatch.py:1–8`·A3는 "per-worker 30s timeout via `asyncio.gather`"라 표현하나, 실제 타임아웃은 `httpx.AsyncClient(timeout=timeout_s)`(dispatch.py:33)의 connect/read/write/pool **개별** 타임아웃. `test_timeout`은 통과(느린 worker→TimeoutException→gap)하나, read 타임아웃 미만으로 바이트를 조금씩 흘리는 worker는 총 wall-clock을 초과할 수 있음 | 두 선택: (a) 의도가 "HTTP 타임아웃"이면 docstring을 정정("per-worker timeout via httpx client timeout"), (b) 진짜 단일 wall-clock 마감을 원하면 `dispatch_one`을 `asyncio.wait_for(..., timeout_s)`로 감싸기. **권장: (b)** — `asyncio.wait_for`로 worker당 단일 마감 보장 + `test_timeout` 재확인 |

## 수정 Todolist
- [x] **O2-a**: `plan_dimensions` 매칭을 부분문자열 → 명시 토큰 매칭으로 교체(예: fact를 `dim:onchain` 형태 태그로 저장하거나, fact 토큰 집합과 dimension 정확 비교) → verify: `test_planner_longterm_read` 통과 + "fact가 다른 dimension 단어를 우연히 포함해도 오선택 안 함" 신규 단정 추가
- [x] **O2-c**: `SqliteLongTermMemory.add_facts` 또는 호출부에 dedup/상한 → verify: 동일 fact 반복 run 후 facts 무한 증가 안 함을 검증하는 테스트
- [x] **O1**: `dispatch_one` 호출을 `asyncio.wait_for(timeout_s)`로 감싸 worker당 단일 wall-clock 마감 보장, docstring을 실제 메커니즘과 일치시킴 → verify: `test_timeout` 통과 유지(필요 시 trickle-byte 케이스 추가)
- [ ] **C1 연계**: `synthesize.py:43` evidence concat에 `[:N]` 방어 슬라이스 도입 여부 결정(증거 폭주 방지) → verify: 도입 시 `test_partial`/`test_zero_artifact` 통과 유지
