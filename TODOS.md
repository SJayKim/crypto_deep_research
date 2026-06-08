# TODOS

Deferred work captured during `/plan-eng-review` on 2026-06-08. None of these
expand the current M0-M5 vertical slice; they are explicitly post-slice.

---

## 1. Approach C enhancements (dynamic planner + tiered distillation + claim verifier)

- **What:** Upgrade the orchestrator to plan the worker set dynamically (from
  query + memory, not always all 4), produce multi-tier distillation (summaries
  at multiple zoom levels), and add a verifier node that checks worker claims
  before they enter the synthesis report.
- **Why:** Dynamic planning and claim verification are first-class 2026 agent
  concepts in their own right. DESIGN.md (Approach C) notes these "graft onto B
  once B works."
- **Pros:** Real additional learning value; reuses the B spine unchanged.
- **Cons:** Meaningful scope; pure distraction until the basic slice runs end to end.
- **Context:** B's synthesizer currently merges artifacts flatly and the planner
  picks a static worker set. C makes both adaptive. Start at the orchestrator
  `planner` and `synthesize` nodes.
- **Depends on / blocked by:** B vertical slice complete (M0-M4 working).

## 2. Official `a2a` SDK variant

- **What:** Rebuild the A2A transport on the official `a2a` Python SDK and run it
  side by side with the hand-rolled JSON-RPC implementation.
- **Why:** The hand-rolled wire (decision A1) is for *seeing* the protocol; the
  SDK is what real teams use. Building both shows exactly what the SDK abstracts.
- **Pros:** Production-shape fidelity; concrete before/after comparison.
- **Cons:** SDK churn/setup cost; redundant with the working hand-rolled path.
- **Context:** Swap only the A2A server/client layer in `workers/` and the
  orchestrator `dispatch` node; contracts and graph logic stay identical.
- **Depends on / blocked by:** M2 hand-rolled A2A wire working.

## 3. JSON-Schema shared-contracts variant

- **What:** Replace the shared Python `contracts/` package with a language-neutral
  JSON-Schema file that each service validates against independently.
- **Why:** Real, independently-deployed services can't import each other's code;
  they share a schema. This is the "how it's really done" version of decision C5.
- **Pros:** Teaches true service decoupling; mirrors real distributed systems.
- **Cons:** More ceremony (codegen/validation) than a shared package for one repo.
- **Context:** Generate Pydantic models from the schema, or validate raw dicts at
  each boundary. Touches `contracts/` and every service's deserialization edge.
- **Depends on / blocked by:** Contracts stable (post-M3).

## 4. In-process LangGraph `Send` fan-out comparison

- **What:** Build a LangGraph `Send` in-process fan-out version of the orchestrator
  alongside the A2A (cross-process) version.
- **Why:** Feeling the contrast between in-graph dispatch (`Send`) and cross-process
  dispatch (`asyncio.gather` over A2A) is the clearest way to internalize *why*
  `Send` cannot cross the process boundary — the trap caught at decision P9.
- **Pros:** Cements the isolation concept by showing what breaks it.
- **Cons:** Maintains two dispatch paths; only valuable as a learning artifact.
- **Context:** A second orchestrator entrypoint that runs workers as in-graph nodes
  via `Send`; compare isolation guarantees and latency against the A2A path.
- **Depends on / blocked by:** B vertical slice working.
