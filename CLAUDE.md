# CLAUDE.md

## Behavioral Guidelines (Karpathy)

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

## Commands

> Assumed Python toolchain — no `pyproject.toml` yet; adjust these when it is set up.
- Install: `uv sync`
- Test: `uv run pytest` (no watch mode)
- Lint: `uv run ruff check .`
- Format: `uv run ruff format .`
- Typecheck: `uv run mypy .`

## Project-Specific Gotchas
<!-- Reflection으로 누적됨. 초기에는 비워둠. -->

## Measurable Conventions
- Agent state must use typed schemas (Pydantic / TypedDict) — no untyped `dict`.
- Functions over 30 lines must be split.
- No live API calls in tests — mock CoinGecko / Binance / Upbit responses. Anthropic LLM: real only in worker-behavior + eval tests; stub (fake artifact/LLM) in deterministic tests (validators, timeout, MCP-down, zero/partial-artifact, memory, isolation-bound).
- Never hardcode API keys — load from `.env` (see `.env.example`).

## Self-Reflection on Errors
When an error, exception, test failure, or unexpected behavior occurs during
this session, reflect AUTONOMOUSLY — do not wait for the user to point it out:

1. STOP. Do not patch the symptom or suppress the error.
2. Analyze the root cause: the actual failure mode (not just the message); why
   it happened (trace back to the originating decision or assumption); whether a
   silent assumption, missing context, or ignored convention caused it; whether
   it is an instance of a pattern that could recur.
3. Fix the root cause, not the symptom.
4. Ask: "Would a rule in this CLAUDE.md have prevented this error?"
   - YES → propose a one-line, specific, measurable rule for the relevant
     section (Gotchas / Conventions). Show the change and wait for confirmation.
   - NO → log the lesson to memory instead (transient issue, not a project rule).

Goal: prevent the same CLASS of error from recurring. Every error is a free lesson.

## Project Context
deep_research — 코인 정보를 수집·분석해주는 deep research **multi-agent** 시스템.
Python + LangGraph로 orchestrator + sub-agent 그래프를 구성한다.
데이터 소스: CoinGecko API(시세·메타데이터), Binance API(실시간 시세·오더북), Upbit API(국내·원화 마켓).
에이전트가 외부 데이터를 가져오므로 prompt injection · rate limit · API 키 노출에 주의한다.
