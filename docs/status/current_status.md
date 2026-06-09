# 현재 상태 (current_status)

**일시:** 2026-06-09 11:06

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
- **커밋 상태:** M0 + M1 + M2 + 스펙 문서 전부 **미커밋** (리포 커밋은 `471c17f`
  하나뿐, `CHECKPOINT_MODE=explicit`).

## Recommended next item
1. (선택) **라이브 테스트 실행:** `.env`에 `ANTHROPIC_API_KEY` 넣고 `uv run pytest -q`
   → T7(워커) + T8(A2A) 라이브 종단 확인 (현재 2 skipped).
2. (선택) **커밋:** 4개로 분리 제안 — (a) 스펙 문서 (b) M0 scaffold/contracts
   (c) M1 worker + MCP 서버 (d) M2 A2A 서비스 + orchestrator.
3. **M3 — Fan-out + synthesizer + long-term READ** (`docs/specs/phases/M3.md`):
   2번째 워커 추가 후 `dispatch.py`를 `asyncio.gather` fan-out으로 일반화(Send 금지),
   `app.py`에 planner(long-term READ)/synthesize 노드 삽입, `workers/base.py`로
   공통부 추출(C6).
4. 보류 항목은 `TODOS.md` 참조 (Approach C / 공식 SDK·JSON-Schema·in-proc Send 변형).
