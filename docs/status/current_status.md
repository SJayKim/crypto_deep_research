# 현재 상태 (current_status)

**일시:** 2026-06-10 (M0~M5 리뷰 수정 배치 반영 갱신)

## 진행한 내용
- 프로젝트 초기 세팅 완료: `CLAUDE.md`(Karpathy 4원칙 verbatim + Commands/Self-Reflection/Project Context), `.gitignore`, `.env.example`(CoinGecko/Binance/Upbit/Anthropic), 보안 hook(`.claude/hooks/protect-files.ps1` + `settings.json`), `git init`.
- `/office-hours` 진행 → 구현 방향 확정.
  - 목표: **아키텍처 학습 우선** (코인 도메인은 핑계, 5개 2026 개념 학습이 핵심).
  - 첫 마일스톤: **수직 슬라이스 1개 완주** ("analyze BTC now").
  - 아키텍처: **B — 서비스 분리, 실제 MCP + 실제 A2A 와이어 프로토콜** (도메인은 stub 유지).
  - 전제 5개 합의 (도메인 stub 우선 / 분해 가능한 쿼리 / orchestrator는 raw context 안 봄 / MCP·A2A 분리 / 메모리 레이어별 트리거).
- 설계 문서 작성 + 독립 리뷰어 적용(7/10, 이슈 수정) → `docs/DESIGN.md` **APPROVED**.
- **`/plan-eng-review` 완료** (2026-06-08) → 결정 10건 + 외부 리뷰어 보정 3건 잠금.
  `docs/DESIGN.md` 의 "Locked Decisions — Eng Review" 섹션 + `TODOS.md` 생성.
  - 핵심 결정: A2A는 직접 짠 JSON-RPC / 분배는 `asyncio.gather`(Send 금지) /
    `WorkerArtifact` Pydantic 검증 + isolation 테스트 / worker별 checkpointer DB.
  - 마일스톤 보정: long-term **READ** 트리거를 M4→**M3**(fan-out)으로 당김.
  - 성공기준 보정: 부분 실패(1/4) 시 리포트에 dimension 커버리지 명시 + 테스트.
- 에픽 분할(2026-06-09): `docs/specs/M0-M5-vertical-slice-epic.md`(인덱스) +
  `docs/specs/phases/M0~M5.md`(마일스톤별 실행 문서).
- **M0 완료·검증(2026-06-09):** `uv` scaffold + `pyproject.toml` + 공유 `contracts/`
  패키지(`artifact`/`report`/`a2a`/`mcp_tools`/`memory`) + `wiring.py` + 검증 테스트.
  게이트 통과(ruff/mypy/pytest). TLS 인터셉션 → `[tool.uv] system-certs = true`로 해결.
- **M1 완료·검증(2026-06-09):** streamable-HTTP MCP 서버(4툴, `FixtureSource`) +
  `market-worker` LangGraph 에이전트(`data→reason→distill`, 직접 호출) + BTC 픽스처 +
  T7/T7b 테스트. 게이트 전부 green: **pytest 11 passed, 1 skipped**.
  - 결정: LLM 스택 `langchain-anthropic` + 모델 `claude-sonnet-4-6`; 워커는 MCP
    클라이언트로 직접 호출(어댑터 없음); MCP 실패 시 LLM 호출 전에 `status="failed"`로
    단락(A3, 키 불필요); distill이 `WorkerArtifact` 경계 강제(A2).
  - **caveat:** `ANTHROPIC_API_KEY` 미설정 → 실 Anthropic 동작 테스트(T7)는 skip 상태.
    스키마·코드는 연결됨, 키만 넣으면 AC#2/#3 종단 검증됨.
- **M2 완료·검증(2026-06-09):** `market-worker`를 직접 짠 JSON-RPC 2.0 A2A 서비스로
  래핑. `workers/market/service.py`(Starlette: `POST /` analyze + `GET
  /.well-known/agent.json`) + orchestrator `dispatch.py`(httpx)/`app.py`(최소
  LangGraph plan→dispatch→return) + `tests/test_a2a_market.py`. 게이트 전부 green:
  **pytest 14 passed, 2 skipped**.
  - 결정: HTTP 서버는 Starlette(기존 FastMCP 스택과 일치), "직접 짠 와이어"는
    JSON-RPC 프로토콜을 직접 검증하는 것; `analyze_market`는 내부에서 `asyncio.run`을
    쓰므로 ASGI 핸들러에서 `asyncio.to_thread`로 오프로드(중첩 이벤트루프 회피).
  - E2E(T8)는 dead-MCP 경로(`status="failed"`)로 실 loopback 소켓 라운드트립을 키
    없이 결정적으로 검증; 라이브 happy-path(status="ok")는 skipif-key.
  - `httpx`/`starlette`를 직접 의존성으로 승격(이미 transitive). 에이전트 로직 불변.
  - **caveat:** 라이브 A2A 라운드트립(T8, status="ok")은 키 없어 skip(1건).
- **M3 완료·검증(2026-06-09):** Fan-out + synthesizer + long-term READ + 공통 하네스
  추출 + 나머지 워커 3개.
  - `dispatch.py`에 `fan_out`(`asyncio.gather`, P9 — Send 금지) + `_dispatch_or_gap`
    (워커별 timeout → `DimensionGap`, A3).
  - `orchestrator/synthesize.py`: artifact 병합 + `dimensions_ok`/`dimensions_unavailable`
    명시 + status `ok|partial|failed`(TENSION-C).
  - `planner.py`: `discover`(Agent Card → dimension 레지스트리, AC#7) +
    `plan_dimensions`(long-term READ, TENSION-B).
  - `app.py`: `plan → dispatch → synthesize` LangGraph로 일반화.
  - `workers/base.py` 공통 하네스 추출(C6): `build_worker_graph`(data→work/fail) +
    `llm_distill`(A2) + `build_worker_app`(A2A 서비스).
  - 워커 3개 추가: `orderbook`(결정적), `sentiment`(LLM), `onchain`(결정적).
- **M4 완료·검증(2026-06-09):** 레이어드 메모리 실트리거 연결.
  - episodic(`SqliteEpisodicMemory`: `last_for`/`put`) + long-term
    (`SqliteLongTermMemory`: `watchlist`/`facts`/`add_facts`), 단일 `orchestrator.db`
    단독 소유(A4). MCP 서버 stateless.
  - `run_orchestrator`: run 시작 episodic READ → seed, run 끝 episodic `put` +
    long-term `add_facts`.
  - working(`memory/working.py`, 워커 checkpointer DB)은 구현·테스트 완료.
    (라이브 경로 미연결 gap → **2026-06-10 W2로 해소**: `serve_worker.__main__`이
    `worker_checkpointer`를 열어 `build_app(cp)`로 주입.)
- **M5 완료·검증(2026-06-09):** 라이브 데이터 스왑 + 패키징.
  - `CoinGeckoSource`(`get_ohlcv` 라이브, 429 retry/backoff; 나머지 3툴은 fixture
    위임) + `source_from_env`(`COIN_DATA_SOURCE` env). 에이전트 코드 불변(AC#2).
  - `Dockerfile` + `docker-compose.yml`(6 프로세스) + `serve_worker.py`(`WORKER_KIND`)
    + `mcp_server/__main__`(`MCP_HOST`).
- **아키텍처 맵 작성:** `docs/ARCHITECTURE-MAP.md`(토폴로지·요청흐름·워커그래프 Mermaid
  다이어그램 + 설계노드↔코드 매핑 + 코드↔설계 갭 2건).
- **M0~M5 코드리뷰 + 수정 배치 완료(2026-06-10):** `docs/reviews/README.md` fix plan의
  코드 항목 전부 완료 — W3/W6/W4(워커 수정), W1(`episodic_seed` 워커 소비),
  W2(라이브 checkpointer 주입), O2(planner 토큰 매칭 + `add_facts` dedup),
  O1(`asyncio.wait_for` wall-clock 마감), WC1(`tests/test_wiring.py`),
  C2(`WorkingMemory` 주석).
- **게이트 전부 green(2026-06-10 재검증):** pytest **54 passed, 2 skipped**, ruff clean,
  mypy clean(60 files). skip 2건 = `ANTHROPIC_API_KEY` 필요한 라이브 테스트
  (T7 워커, T8 A2A happy-path).
- **커밋 상태:** 리뷰 수정 배치까지 `dad06eb`("fix: M0-M5 review fixes")로 **커밋 완료**.

## Recommended next item
수직 슬라이스(M0~M5)는 코드·게이트 기준 **완주**, 리뷰 수정 배치까지 반영.
남은 것은 라이브 종단 확인, 보류 항목.

1. **라이브 종단 확인:** `.env`에 `ANTHROPIC_API_KEY`(+ M5 라이브는 `COINGECKO_API_KEY`)
   넣고 `uv run pytest -q` → T7(워커)·T8(A2A) happy-path 확인(현재 2 skipped).
   `docker compose up -d` + `docker compose run --rm orchestrator`로 6 프로세스 종단(AC#5).
2. **코드↔설계 갭 2건 — 해소(2026-06-10):** W2(라이브 checkpointer 주입) +
   W1(`episodic_seed` 워커 소비). 상세: `docs/ARCHITECTURE-MAP.md` §8.
3. **보류 항목:** `TODOS.md` 참조 (Approach C / 공식 SDK·JSON-Schema·in-proc Send 변형).
