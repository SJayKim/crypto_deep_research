# EPIC: "analyze BTC now" vertical slice (Approach B, M0–M5)

> Authored by `/spec` on 2026-06-08. Source of truth: `docs/DESIGN.md` (+ Locked
> Decisions). Non-functional constraints: `CLAUDE.md`. Status reference:
> `docs/status/current_status.md`. Deferred work in `TODOS.md` is **out of scope**
> (see "Out of Scope"). No GitHub remote, so this spec is a local doc, not an issue.

---

## Context

`deep_research` is a **learning vehicle**: the coin domain is the excuse, the goal
is to feel every 2026 core agent concept once (orchestrator-worker, context
isolation, distillation, layered memory, MCP vs A2A). Learning fidelity is the
north star, not analysis quality (DESIGN D1). The chosen architecture is
**Approach B**: orchestrator + 4 workers + 1 MCP server as separate processes,
A2A as a real hand-rolled JSON-RPC wire, context isolation enforced by process
boundaries. This epic delivers ONE full vertical slice (`analyze BTC now`) across
six milestones, contracts first.

Who cares: solo builder, learning. The "value delivered" is the working slice plus
the assertions that prove each concept is real, not simulated.

## Current State (verified 2026-06-08)

Greenfield. The repo holds docs + config only; no Python, no package, no scaffold.

| Path | Exists | Note |
|------|--------|------|
| `docs/DESIGN.md`, `TODOS.md`, `docs/status/current_status.md` | ✅ | Design approved, eng-reviewed |
| `CLAUDE.md`, `.gitignore`, `.env.example` | ✅ | `.env.example` has CoinGecko/Binance/Upbit/Anthropic keys |
| `.claude/hooks/protect-files.ps1` + `settings.json` | ✅ | Security hook |
| `pyproject.toml` | ❌ | M0 creates it |
| `deep_research/` package, `contracts/`, `orchestrator/`, `workers/`, `mcp_server/`, `memory/` | ❌ | M0–M5 create them |
| any `*.py` | ❌ | M0 is the first code |

So M0 is the genuine next action; nothing exists to refactor or preserve.

## Architecture

Six services. Five 2026 concepts, each pinned to a component (DESIGN
"Concept-to-component map"):

| Concept | Where it lives | What makes it real |
|---------|----------------|--------------------|
| Orchestrator-worker | Orchestrator plans + dispatches to worker services | Workers are separate processes, dispatched over A2A |
| Context isolation | Each worker = own process + own LLM context | Orchestrator literally cannot read worker raw context |
| Distillation | Each worker's distill node summarizes its own context | `WorkerArtifact` validators bound the output (≤5 key points, capped lengths, typed evidence) |
| Layered memory | working / episodic / long-term with triggers | Planner reads long-term to pick workers; episodic seeds the run |
| MCP / A2A | MCP = coin-data tools; A2A = orchestrator↔worker | Two distinct protocols, two distinct boundaries, not conflated |

### Proposed package layout (M0 establishes it)

Flat `deep_research/` package at repo root. CLI entry `python -m deep_research "analyze BTC now"`.

```
deep_research/
  __main__.py            # CLI entry → orchestrator
  wiring.py              # static service URLs from env; data-driven worker registry
  contracts/            # C5: one shared package imported by ALL six services
    a2a.py              # JSON-RPC task/result models + AgentCard
    mcp_tools.py        # 4 tool I/O schemas
    artifact.py         # WorkerArtifact (+ validators)
    report.py           # SynthesisReport (+ coverage fields)
    memory.py           # WorkingMemory / EpisodicMemory / LongTermMemory protocols + RunRecord
  mcp_server/
    server.py           # streamable-HTTP MCP server, 4 tools, stateless read-only
    sources/
      base.py           # DataSource interface
      fixture.py        # FixtureSource (day one)
      coingecko.py      # CoinGeckoSource (M5)
      fixtures/         # JSON fixtures per tool/symbol
  orchestrator/
    app.py              # LangGraph app: plan → dispatch → synthesize
    planner.py          # reads long-term memory, picks worker set
    dispatch.py         # asyncio.gather over A2A (P9: NOT LangGraph Send)
    synthesize.py       # merges artifacts → SynthesisReport
  workers/
    base.py             # shared Worker harness (extracted after 2nd worker — C6)
    market/   agent.py + service.py
    orderbook/ sentiment/ onchain/   (same shape)
  memory/
    working.py          # per-run scratchpad via LangGraph checkpointer
    episodic.py         # past analyses per coin (SQLite)
    longterm.py         # watchlist + learned facts (SQLite)
tests/
```

`service.py` per worker = A2A JSON-RPC server + Agent Card at
`/.well-known/agent.json`. DB topology (A4): each worker owns its own checkpointer
DB; the orchestrator solely owns the episodic + long-term DB; MCP is stateless.

## Locked Decisions (do NOT re-litigate)

These are settled by `/plan-eng-review`; treat as constraints, not options:

| # | Constraint |
|---|-----------|
| A1 | A2A = hand-rolled minimal JSON-RPC 2.0 + static Agent Card (NOT the official `a2a` SDK) |
| A2 | Distillation enforced by `WorkerArtifact` Pydantic validators + flagship isolation test |
| A3 | Per-worker 30s timeout (env-configurable) via `asyncio.gather`; zero-artifact → `status=failed`, CLI non-zero exit |
| A4 | Each worker owns its checkpointer DB; orchestrator owns episodic + long-term DB; MCP stateless |
| C5 | One shared `contracts/` Python package imported by all six services |
| C6 | Build market-worker concretely first; extract the shared base harness only after the 2nd worker (rule of three) |
| P9 | Fan-out = `asyncio.gather` over A2A. **NOT** LangGraph `Send` (Send cannot cross the process boundary; using it silently collapses B into A) |
| T7/T7b | Real Anthropic in worker-behavior + eval tests; deterministic stub in validator/timeout/MCP-down/zero+partial-artifact/memory/isolation-bound tests |
| T8 | Routine E2E = in-process ASGI on loopback ports (real JSON-RPC/HTTP); M5 docker-compose is the single real-OS-process-boundary proof |
| TENSION-B | Long-term **READ** trigger (planner picks worker set) ships in **M3**, not M4 |
| TENSION-C | Synthesis report carries explicit per-dimension coverage; a test asserts a 1-of-4 run is visibly partial |

## Shared Contracts (M0 deliverable, zero design decisions left)

Concrete Pydantic v2 sketches. Caps are normative.

```python
# contracts/artifact.py
Dimension = Literal["market", "orderbook", "sentiment", "onchain"]

class Evidence(BaseModel):
    metric: str = Field(max_length=64)          # e.g. "RSI_14"
    value: float | str                          # self-contained; never a pointer into worker context

class WorkerArtifact(BaseModel):
    dimension: Dimension
    status: Literal["ok", "failed"]
    headline: str = Field(max_length=200)
    key_points: list[str] = Field(max_length=5)         # ≤5 points (A2)
    evidence: list[Evidence] = Field(default_factory=list, max_length=10)

    @field_validator("key_points")
    @classmethod
    def _cap_point_len(cls, v):                          # each point ≤200 chars
        if any(len(p) > 200 for p in v):
            raise ValueError("key_point exceeds 200 chars")
        return v
```

```python
# contracts/report.py
class DimensionGap(BaseModel):
    dimension: Dimension
    reason: str                                          # e.g. "timeout", "mcp_down"

class SynthesisReport(BaseModel):
    symbol: str
    status: Literal["ok", "partial", "failed"]
    headline: str = Field(max_length=200)
    key_points: list[str] = Field(max_length=10)
    evidence: list[Evidence] = Field(default_factory=list)
    dimensions_ok: list[Dimension]
    dimensions_unavailable: list[DimensionGap]           # TENSION-C
```

```python
# contracts/a2a.py
class TaskParams(BaseModel):
    symbol: str
    run_id: str
    episodic_seed: dict | None = None                    # last-run summary the orchestrator may pass

class JsonRpcRequest(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str
    method: Literal["analyze"]
    params: TaskParams

class JsonRpcError(BaseModel):
    code: int
    message: str

class JsonRpcResponse(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str
    result: WorkerArtifact | None = None
    error: JsonRpcError | None = None

class AgentCard(BaseModel):                              # served at /.well-known/agent.json
    name: str
    description: str
    url: str
    version: str
    skills: list[str]                                    # e.g. ["analyze:market"]
```

```python
# contracts/mcp_tools.py  (tool I/O — tools: get_ohlcv, get_orderbook, get_news, get_onchain)
class OHLCVBar(BaseModel):
    ts: int; open: float; high: float; low: float; close: float; volume: float
class OHLCV(BaseModel):
    symbol: str; interval: str; bars: list[OHLCVBar]

class OrderbookLevel(BaseModel):
    price: float; size: float
class Orderbook(BaseModel):
    symbol: str; bids: list[OrderbookLevel]; asks: list[OrderbookLevel]

class NewsItem(BaseModel):
    title: str; source: str; sentiment: float            # -1.0..1.0
class News(BaseModel):
    symbol: str; items: list[NewsItem]

class OnchainMetrics(BaseModel):
    symbol: str; active_addresses: int; tx_volume: float; exchange_netflow: float
```

```python
# contracts/memory.py
class RunRecord(BaseModel):
    run_id: str; symbol: str; ts: int; report: SynthesisReport

class WorkingMemory(Protocol):
    def note(self, run_id: str, key: str, value: str) -> None: ...      # write: worker records notes
    def read(self, run_id: str) -> dict[str, str]: ...                  # read: distill node

class EpisodicMemory(Protocol):
    def last_for(self, symbol: str) -> RunRecord | None: ...            # read: run start
    def put(self, record: RunRecord) -> None: ...                       # write: run end

class LongTermMemory(Protocol):
    def watchlist(self) -> list[str]: ...                               # read: planner
    def facts(self, symbol: str) -> list[str]: ...                      # read: planner
    def add_facts(self, symbol: str, facts: list[str]) -> None: ...     # write: run end
```

Wiring pin (M0): one env var per service URL + MCP URL + `WORKER_TIMEOUT_S`
(default 30, A3); worker registry read from a data-driven env list so adding a
worker never edits `orchestrator/`; Agent Cards at `/.well-known/agent.json`;
MCP transport = streamable HTTP.

## Child Issues

| # | Milestone | Priority | Effort (nominal) | Status | Depends on |
|---|-----------|----------|------------------|--------|-----------|
| M0 | Contracts & scaffold | Critical | S–M (~½ day) | Not started | — |
| M1 | One worker, direct (market + MCP fixtures) | Critical | M (~1 day) | Blocked | M0 |
| M2 | One worker over A2A (first over-the-wire slice) | Critical | M (~1 day) | Blocked | M1 |
| M3 | Fan-out + synthesizer + long-term READ | High | L (~2–3 days) | Blocked | M2 |
| M4 | Memory writes + episodic/long-term round-trip | High | M (~1 day) | Blocked | M3 |
| M5 | Live CoinGecko swap + docker-compose packaging | Medium | M (~1–1.5 days) | Blocked | M4 |

Effort is learning-paced and nominal; wall-clock varies with how much each concept
is being learned for the first time. Per-component breakdown is in each child below.

## Dependency Graph

```
M0 Contracts ──> M1 Direct worker ──> M2 A2A wire ──> M3 Fan-out + long-term READ ──> M4 Memory round-trip ──> M5 Live + compose
                                                          │
                                                          └─ after base-harness extract, 3 worktree lanes run in parallel:
                                                             [orderbook] [sentiment] [onchain]   (+ memory as a 4th lane into M4)
```

Linear spine by milestone. The only intra-milestone parallelism is inside M3/M4:
once the base Worker harness is extracted (mid-M3, per C6), `workers/orderbook/`,
`workers/sentiment/`, `workers/onchain/` and the `memory/` work each touch disjoint
dirs and can run as separate worktree lanes (DESIGN "Worktree parallelization").

## Sequencing Rationale

- **M0 before everything**: contracts are imported by all six services (C5). Until
  the shared types exist, no service can be written without inventing types others
  must then match. Defining them once, first, removes that whole class of rework.
- **M1 before M2 (direct before wire)**: prove `data → reason → distill` with the
  MCP server and a real LLM worker *before* adding the A2A transport. Debugging the
  reasoning loop and the wire at the same time doubles the surface; M1 isolates the
  worker logic, M2 isolates the protocol.
- **M2 before M3**: one worker over the wire proves the A2A boundary end to end.
  Fan-out is only meaningful once a single dispatch works; adding parallelism to an
  unproven transport hides which layer failed.
- **M3 before M4 (READ before WRITE)**: TENSION-B pulls the long-term READ trigger
  into M3 because it shapes orchestration (the planner picks the worker set from
  long-term memory). The episodic/long-term WRITE path and the round-trip close in
  M4. Read-then-write also lets M3 run against seeded fixtures before M4 makes the
  store self-populating.
- **M4 before M5**: the slice must be correct in-process (loopback ASGI, T8) before
  paying for live data + container packaging. M5 swaps one DataSource and adds
  docker-compose; doing it earlier would debug infra against unproven logic.

---

## M0 — Contracts & scaffold

**Scope.** `pyproject.toml` (uv, ruff, mypy, pytest, pre-commit), the package
layout above, all `contracts/` models, `wiring.py`, the `sources/fixtures/`
directory (empty placeholder), and service-URL env vars added to `.env.example`.
**No service logic, no agent, no server.**

**Acceptance criteria** (numbered, pass/fail):
1. `uv sync` succeeds; `python -c "import deep_research.contracts"` works.
2. `uv run ruff check .` and `uv run mypy .` pass clean on `contracts/` + `wiring.py`.
3. `WorkerArtifact` rejects 6 key_points, rejects a >200-char key_point, and rejects
   a >200-char headline (3 deterministic-stub validator unit tests, T7b).
4. `SynthesisReport` round-trips `status` ∈ {ok, partial, failed} with populated
   `dimensions_ok` / `dimensions_unavailable`.
5. `wiring.py` reads the worker URL list + `WORKER_TIMEOUT_S` (default 30) from env;
   a missing var raises a clear error (not a silent default for URLs).
6. No function exceeds 30 lines; no untyped `dict` in contract models (CLAUDE.md).

**Files.** `pyproject.toml`, `deep_research/contracts/{a2a,mcp_tools,artifact,report,memory}.py`,
`deep_research/wiring.py`, `.env.example` (append service URLs), `tests/test_contracts.py`.

**Effort.** Schemas ~2h + scaffold/tooling ~1h + validator tests ~1h.

**Applies.** A1, A2 (validator half), A3 (timeout env), A4 (interface only), C5, TENSION-C (report fields).

---

## M1 — One worker, direct

**Scope.** MCP server (streamable HTTP) exposing all 4 tools backed by
`FixtureSource`; `market-worker` as a LangGraph agent (`data → reason → distill`)
called **directly** (no A2A); BTC fixtures for the 4 tools. Market-worker uses LLM
reasoning (DESIGN per-worker decision); distill node emits a valid bounded
`WorkerArtifact`.

**Acceptance criteria:**
1. MCP server responds to all 4 tool calls over streamable HTTP with the schemas in
   `contracts/mcp_tools.py`; tools are stateless and read-only (4 concurrent calls
   return identical data).
2. Calling `market-worker` directly with `"BTC"` pulls OHLCV via MCP, reasons, and
   returns a `WorkerArtifact(dimension="market", status="ok")` that passes all
   validators.
3. Worker-behavior test runs against **real Anthropic** and asserts the artifact is
   non-trivial (headline non-empty, ≥1 key point, ≥1 evidence) (T7).
4. MCP-down test uses a **deterministic stub**: MCP unreachable → worker returns
   `status="failed"`, never raises into the caller (T7b, A3 shape).

**Files.** `mcp_server/server.py`, `mcp_server/sources/{base,fixture}.py`,
`mcp_server/sources/fixtures/btc_*.json`, `workers/market/agent.py`,
`tests/test_market_worker.py`, `tests/test_mcp_server.py`.

**Effort.** MCP server + fixtures ~3h, market-worker agent ~3h, tests ~2h.

**Applies.** A2 (distill bounds), MCP boundary, T7/T7b.

---

## M2 — One worker over A2A

**Scope.** Wrap `market-worker` as an A2A JSON-RPC 2.0 service (A1) with a static
Agent Card at `/.well-known/agent.json`; orchestrator `dispatch` node calls it over
A2A. First over-the-wire vertical slice. Hand-rolled wire only (A1 already settled
the SDK question).

**Acceptance criteria:**
1. `market-worker/service.py` serves `POST` JSON-RPC `analyze` and `GET /.well-known/agent.json`.
2. Orchestrator dispatches an A2A `analyze` task and receives a `WorkerArtifact`
   back; request/response validate against `contracts/a2a.py`.
3. E2E test runs the worker as an in-process ASGI app on a loopback port (T8) and
   asserts a real JSON-RPC round-trip (not an in-proc function call).
4. A malformed JSON-RPC request returns a structured `JsonRpcError`, not a 500 stack trace.

**Files.** `workers/market/service.py`, `orchestrator/dispatch.py` (single-worker
form), `orchestrator/app.py` (minimal plan→dispatch→return), `tests/test_a2a_market.py`.

**Effort.** A2A server + Agent Card ~3h, dispatch client ~2h, E2E ~2h.

**Applies.** A1, T8, context isolation (orchestrator receives only the artifact).

---

## M3 — Fan-out + synthesizer + long-term READ

**Scope.** Add `orderbook-worker` as the 2nd worker, then extract `workers/base.py`
(C6 rule of three), then add `sentiment-worker` + `onchain-worker`. `asyncio.gather`
fan-out over A2A (P9, never `Send`). Synthesizer merges artifacts into a
`SynthesisReport` with per-dimension coverage (TENSION-C). Planner reads long-term
memory to pick the worker set (TENSION-B long-term READ). Partial-failure policy
(A3): synthesize on ≥1 artifact, mark the rest unavailable; per-worker 30s timeout.

**Acceptance criteria:**
1. All 4 workers dispatch in parallel via `asyncio.gather` over A2A; total latency ≈
   slowest worker, not the sum (proves parallel, not sequential).
2. **Flagship isolation test (A2):** feed a 1000-row OHLCV fixture; assert (a) the
   market artifact is bounded (≤5 key_points, no raw array) AND (b) orchestrator
   state holds **zero** raw OHLCV arrays at any point (stub LLM, T7b).
3. **Partial test (TENSION-C):** force 1 worker to fail; report has
   `status="partial"`, the failed dimension in `dimensions_unavailable` with a
   reason, and the CLI surfaces it.
4. **Zero-artifact test (A3):** all 4 fail → `status="failed"`, every dimension
   listed with a reason, CLI exits non-zero.
5. **Timeout test (A3):** a worker exceeding `WORKER_TIMEOUT_S` is marked
   unavailable, not blocking; the gather still returns.
6. Planner reads long-term `watchlist()` / `facts(symbol)` and the chosen worker set
   reflects it (long-term READ trigger, stub memory).
7. `orchestrator/` is untouched when adding workers 3 and 4 (data-driven registry).

**Files.** `workers/{orderbook,sentiment,onchain}/{agent,service}.py`,
`workers/base.py`, `orchestrator/{planner,dispatch,synthesize}.py`,
`tests/test_isolation.py`, `tests/test_partial.py`, `tests/test_zero_artifact.py`,
`tests/test_timeout.py`, `tests/test_planner_longterm_read.py`.

**Effort.** orderbook ~2h, base extract ~2h, sentiment+onchain ~3h, synthesizer ~2h,
planner READ ~1h, the 5 tests ~4h. Largest milestone; split into worktree lanes if
desired (orderbook / sentiment / onchain disjoint).

**Applies.** P9, A2 (flagship), A3, C6, TENSION-B, TENSION-C, T7b, T8.

---

## M4 — Memory writes + round-trip

**Scope.** Episodic write (run end stores `RunRecord`) + read (run start retrieves
last run by symbol); long-term write (run end appends learned facts); working memory
via the LangGraph checkpointer. DB topology per A4: each worker owns its checkpointer
DB; orchestrator solely owns the episodic + long-term DB (single-writer-per-file);
MCP stateless.

**Acceptance criteria:**
1. A second `analyze BTC now` run reads the first via episodic `last_for("BTC")`
   and the run visibly references it (episodic round-trip).
2. A long-term fact written at run end changes the next run's plan (long-term
   WRITE → next-run READ closes the loop started in M3).
3. Each worker's checkpointer DB is a distinct file from the orchestrator's
   episodic/long-term DB (A4 verified by path assertion).
4. Concurrent workers writing their own checkpointer DBs never touch the
   orchestrator DB (single-writer-per-file holds).
5. Memory tests use deterministic stubs, not real LLM (T7b).

**Files.** `memory/{working,episodic,longterm}.py`, orchestrator run-start/run-end
wiring, `tests/test_episodic_roundtrip.py`, `tests/test_longterm_affects_plan.py`,
`tests/test_db_topology.py`.

**Effort.** episodic ~2h, long-term ~2h, working/checkpointer wiring ~2h, tests ~2h.

**Applies.** A4, premise 5 (every layer has a trigger), T7b.

---

## M5 — Live data + packaging

**Scope.** Add `CoinGeckoSource` behind the same MCP tool interface, swap one tool
(`get_ohlcv`) from fixture to live with **zero agent code changes**; the other 3
stay on fixtures. `docker-compose` brings up orchestrator + 4 workers + MCP server +
DB as the single real-OS-process-boundary proof (T8). API key from `.env`,
rate-limit handling on the live source.

**Acceptance criteria:**
1. `docker-compose up` then `python -m deep_research "analyze BTC now"` returns a
   `SynthesisReport` using live CoinGecko for `get_ohlcv`, fixtures for the rest.
2. The fixture→live swap touched only `sources/coingecko.py` + env; no diff under
   `workers/` or `orchestrator/` (proves the MCP tool boundary held).
3. CoinGecko key loads from `.env`; grep finds no hardcoded key (CLAUDE.md).
4. A simulated 429 from CoinGecko is handled (backoff or surfaced as a dimension
   gap), not an unhandled crash. Live calls appear only in this milestone's
   eval-style check, never in the deterministic suite (CLAUDE.md: no live API in tests).
5. Logs show 6 distinct processes under compose (real process-boundary proof).

**Files.** `mcp_server/sources/coingecko.py`, `docker-compose.yml`, per-service
`Dockerfile`(s), `tests/test_source_swap.py` (asserts no agent-code diff path).

**Effort.** CoinGeckoSource + rate limit ~3h, docker-compose + Dockerfiles ~3h,
swap test ~1h.

**Applies.** A4 (MCP stateless), MCP boundary, T8 (compose), CLAUDE.md (keys, no live API in tests).

---

## Testing Strategy

| Layer | What | Where | LLM |
|-------|------|-------|-----|
| Unit | `WorkerArtifact`/`SynthesisReport` validators, planner set-selection, memory CRUD | M0, M3, M4 | stub (T7b) |
| Integration | MCP tool calls, A2A JSON-RPC round-trip, timeout/partial/zero paths | M1–M3 | stub (T7b) |
| E2E (in-proc) | loopback-ASGI full slice, isolation flagship | M2, M3 | stub for isolation; real for behavior |
| Behavior / eval | worker produces a sensible artifact; live CoinGecko sanity | M1, M5 | real Anthropic (T7) |
| Process-boundary | docker-compose 6-process run | M5 | n/a |

LLM boundary is **load-bearing** (T7/T7b, recorded in CLAUDE.md): real Anthropic
only in worker-behavior + eval tests; everything deterministic (validators, timeout,
MCP-down, zero/partial artifact, memory, isolation-bound) uses a stub. Exchange APIs
are never called live in tests; only M5's eval-style check hits CoinGecko.

## Non-Functional Requirements (CLAUDE.md)

1. Agent/contract state uses typed schemas (Pydantic / TypedDict); no untyped `dict`.
2. No function over 30 lines (split it).
3. API keys load from `.env` only; never hardcoded; `.env.example` documents them.
4. Quality gate (local, pre-commit): `ruff check`, `ruff format`, `mypy`, `pytest`.
   No GitHub Actions until a remote exists (DESIGN: CI on a no-remote solo repo is
   gold-plating).

## Definition of Done (epic)

1. `analyze BTC now` returns a `SynthesisReport` (local processes M1–M4, `docker-compose up` at M5).
2. Orchestrator state provably holds only distilled artifacts — the M3 flagship
   isolation test asserts zero raw OHLCV arrays ever enter orchestrator context.
3. A2A calls are real: separate processes, verifiable in logs (loopback M2–M4, OS
   processes M5).
4. MCP server serves all 4 tools; workers connect as MCP clients.
5. Memory works: a second BTC run references the first (episodic); watchlist/facts
   change the plan (long-term).
6. Partial coverage is visible: a 1-of-4 run is marked `partial` with per-dimension
   reasons (TENSION-C); a 0-of-4 run is `failed` and the CLI exits non-zero (A3).
7. The live swap (M5) changed no agent code (MCP boundary held).

## Rollback

Greenfield local repo, no remote, no production. Rollback = `git revert` of the
milestone's commit(s); each milestone is a self-contained commit set. No data
migration risk (SQLite files are local and disposable; delete and re-run). The only
external dependency introduced is CoinGecko at M5, gated behind a DataSource swap, so
reverting M5 returns to all-fixtures with one env/source change.

## Out of Scope (do NOT pull in)

From `TODOS.md` (explicitly post-slice):
- **Approach C** — dynamic planner, multi-tier distillation, claim verifier.
- **Official `a2a` SDK** variant (A1 hand-rolls on purpose).
- **JSON-Schema** language-neutral contracts variant (C5 uses a shared Python package).
- **In-process LangGraph `Send`** fan-out comparison (P9 bans Send in the spine).

Also out of scope for this epic:
- Live **Binance / Upbit** sources (only one live source, CoinGecko, at M5).
- GitHub Actions / remote CI (deferred until a remote exists).
- Auth, multi-user, multi-coin batch runs, a web UI.

## Assumptions (flag for review — correct any and I'll edit)

1. **Python 3.12** for the toolchain pin (mature asyncio, modern typing). DESIGN
   doesn't pin a version.
2. **Flat `deep_research/` package** at repo root (vs `src/` layout). DESIGN left
   the exact layout to implementation; flat is simpler for a learning repo and still
   supports `python -m deep_research`.
3. **onchain-worker reasoning style is decided at M3**, not here. DESIGN specified
   market/sentiment = LLM and orderbook = mostly deterministic, but left onchain
   open; it leans deterministic but the call is the builder's at M3.
4. **Effort numbers are learning-paced nominals**, not commitments.

## Related

- `docs/DESIGN.md` — approved design + Locked Decisions (source of truth).
- `docs/status/current_status.md` — M0 is the next action.
- `TODOS.md` — deferred work (out of scope above).
- `CLAUDE.md` — conventions enforced as non-functional requirements.

## Next action

Start **M0**: scaffold (`uv init`, `pyproject.toml`, package layout) and write the
`contracts/` models with their validator unit tests. Per DESIGN, this is the one
gate everything else imports.
