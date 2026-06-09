# Review 05 — memory

## 대상 파일
- `crypto_deep_research/memory/working.py` — `working_db_path` + `worker_checkpointer`(LangGraph SqliteSaver)
- `crypto_deep_research/memory/episodic.py` — `SqliteEpisodicMemory`(`last_for`/`put`)
- `crypto_deep_research/memory/longterm.py` — `SqliteLongTermMemory`(`watchlist`/`facts`/`add_facts`)

## 대조 spec
- `phases/M4.md` AC#1–#5, locked decision A4(per-worker checkpointer DB vs orchestrator episodic+longterm DB, single-writer), DESIGN premise 5(layer마다 real trigger), `contracts/memory.py` protocols

## 리뷰 체크리스트

### ① Spec 적합성
- [x] episodic: run-start `last_for(symbol)` read, run-end `put(record)` write (episodic.py:26–46; app.py:84,98)
- [x] long-term: planner read(`watchlist`/`facts`), run-end write(`add_facts`) (longterm.py:22–34; app.py:99)
- [x] A4 토폴로지: orchestrator가 단일 `orchestrator.db`에 episodic+longterm 공유(`__main__.py:45`), worker는 자기 `working-<dim>.db`(working.py:18–20) — `test_db_topology`(AC#3/#4)
- [x] `last_for` 결정성: `ORDER BY ts DESC, rowid DESC`로 동초 run도 결정적 (episodic.py:28–30)
- [⚠️] working layer 메커니즘은 존재하나 라이브 worker 미연결 → **W2(04-workers)** 와 동일 근본
- [⚠️] `WorkingMemory.note/read` protocol 구현 부재 → **C2(01-contracts)** 와 동일

### ② 정확성/버그
- [x] `add_facts`가 `executemany`로 배치 insert; 빈 리스트(=failed run의 key_points)면 no-op (longterm.py:30–34)
- [x] `SqliteEpisodicMemory`/`SqliteLongTermMemory`가 `CREATE TABLE IF NOT EXISTS`로 멱등 초기화
- [⚠️] `add_facts`가 dedup/상한 없이 무제한 적재 → 누적 시 `plan_dimensions` 부분문자열 매칭 신호 퇴화 → **O2(03-orchestrator)** 의 저장측 근본
- [△] episodic·longterm이 동일 `orchestrator.db`에 **각자 별도 `sqlite3.connect`** 개설(check_same_thread=False) (episodic.py:18, longterm.py:14) — 단일 프로세스라 OK, WAL 미설정. 정보성

### ③ 보안
- [x] 메모리는 로컬 SQLite 파일, 외부 노출 없음; 키·시크릿 저장 안 함
- [x] 파라미터 바인딩(`?`) 사용 — SQL injection 없음 (episodic/longterm 전체)
- [△] `report`를 JSON 직렬화해 저장(episodic.py:44) — 신뢰된 내부 데이터, 역직렬화는 `SynthesisReport.model_validate_json`로 스키마 검증(episodic.py:38)

### ④ 테스트 커버리지
- [x] `test_episodic_roundtrip`(AC#1), `test_longterm_affects_plan`(AC#2), `test_db_topology`(AC#3/#4) — 모두 T7b 스텁(AC#5)
- [x] working: `test_db_topology`가 `working_db_path`/`worker_checkpointer` 경로·격리 검증
- [△] working layer가 **라이브 run에서 실제로 채워지는지**는 미검증(테스트 전용 호출) — W2 수정 시 보강 대상

## Findings

> 메모리 컴포넌트의 핵심 이슈는 다른 문서에 근본이 있어 **교차참조**로 관리한다(중복 수정 방지).

| ID | 관점 | 심각도 | 근거 | 해결방안(주관할 문서) |
|----|------|--------|------|----------------------|
| **W2**(ref) | spec 적합성 | Med | `working.py`의 `worker_checkpointer`/`working_db_path`가 라이브 경로 미호출 — working layer trigger 부재 | [04-workers](./04-workers.md) W2에서 라이브 주입. 본 문서는 working DB 생성 검증 테스트 보강 책임 |
| **O2**(ref) | 정확성 | Med | `add_facts` 무제한 적재가 planner 부분문자열 매칭과 결합해 신호 퇴화 | [03-orchestrator](./03-orchestrator.md) O2에서 planner 매칭 교체. 본 문서는 `add_facts` dedup/상한 구현 책임 |
| **C2**(ref) | 정합성 | Low | `WorkingMemory.note/read` 구현체 부재 | [01-contracts](./01-contracts.md) C2에서 protocol 주석/정리. 본 문서는 checkpointer가 그 역할을 대체함을 명시 |
| **Mem4** | 견고성 | Low | episodic·longterm이 같은 파일에 별도 connection 2개, WAL 미설정 (episodic.py:18, longterm.py:14). 단일 orchestrator 프로세스라 현재 문제 없음 | 정보성. 동시성 확장 시 단일 connection 공유 또는 `PRAGMA journal_mode=WAL` 고려. **슬라이스 범위상 현행 유지** |

## 수정 Todolist
- [ ] **O2(저장측)**: `SqliteLongTermMemory.add_facts`에 dedup(동일 (symbol,fact) 중복 방지) 또는 상한 → verify: 동일 run 반복 후 facts 행수 무한 증가 안 함을 검증하는 신규 테스트
- [ ] **W2(검증측)**: 라이브 주입(04-workers) 후 `working-<dim>.db`가 실제 run에서 생성/기록됨을 `test_db_topology` 확장 또는 신규 테스트로 단정 → verify: 신규 단정 통과
- [ ] **C2(명시)**: working.py 또는 contracts/memory.py에 "working layer = checkpointer(state-as-scratchpad), note/read protocol 미사용" 주석 → verify: mypy clean, 동작 무변경
- [ ] **Mem4**: 코드 변경 없음(정보성 기록) → verify: 리뷰 합의
