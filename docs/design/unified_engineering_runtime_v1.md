# Unified Engineering Runtime v1

> Status: **Architecture baseline and migration contract**
> Project identity: **Evidence-Grounded AI Engineering Agent**
> Architecture baseline: `c6ee568923babcb0dc3e040ceef1e18e162b02db`
> Current migration: `ARCH-CONTEXT-03`
> Historical Gate facts are immutable; this document defines the only target architecture for `ARCH-RUNTIME-02` through `ARCH-EVAL-08`.

## 1. Purpose and boundary

The project has useful capabilities in several historical Gate lines, but the
Engineering product path has accumulated **Architecture Integration Drift**:
capabilities exist, while control ownership is split between the current
ToolAgent path and older G3/G8 components. This document freezes the boundary
for unifying those capabilities into one Engineering Agent Runtime.

This is a component-migration contract, not a request to rewrite the product.
It does not authorize changing prompts, router rules, guard rules, the frozen
5/4/2 ToolAgent budget, Formal artifacts, or public API schemas outside the
explicit migration stage.

## 2. Current Architecture

### 2.1 Baseline facts at the start of architecture integration

The actual Engineering main chain at the architecture baseline is:

```text
Engineering API / Stream
        |
        v
EngineeringAgentFacade
        |
        v
UnifiedEngineeringRuntime       (route seam; no second loop)
        |
        v
LegacyToolAgentExecutionAdapter
        |
        v
ToolAgentRuntime                 (actual Decision -> Tool -> Observation controller)
        |
        v
Finalization Guard / result
```

The important current-state facts are:

- The Engineering main chain is practically controlled by `ToolAgentRuntime`.
- G3 `Planner` / `QueryPlan`, Query Decomposition, Adaptive Retrieval,
  Multi-query Retrieval, and `MinimalEvidenceVerifier` are implemented or
  historically evaluated, but are not in this Engineering main chain.
- At the ARCH-CONTEXT-03 starting baseline, G8 Context / Standalone Resolver
  is also not in the Engineering main chain. Its historical integration in
  `core/agent_runtime/runtime.py` remains a legacy path and is not rewritten.
- G11 Unified Evidence and G12 Typed Requirement / Finalization Guard are
  **ACTIVE** integration inputs. They do not imply that every historical
  component has already been migrated.
- `P1-OBS-03A-R1-MICRO` is **ACCEPT / CLOSED**. Safe Trace and Rich Activity
  are observational projections and cannot decide or mutate a run outcome.

### 2.2 Migration state after ARCH-CONTEXT-03

ARCH-CONTEXT-03 adds one front component to `UnifiedEngineeringRuntime`:

```text
request
  -> EngineeringContextResolver
  -> EngineeringContextSnapshot.resolved_input
  -> requirement route exactly once
  -> LegacyToolAgentExecutionAdapter
  -> ToolAgentRuntime's existing 5/4/2 execution loop
```

This is not yet the final control plane. ToolAgentRuntime still owns the
execution loop during migration; G3 planning/retrieval/verifier components and
the later unified Evidence/Verification/Finalization ownership remain future
migration stages. The context component is not a second Agent and does not add
a loop, budget ledger, finalization decision, or Tool call.

### 2.3 G8 context contract being migrated

The migration reuses, without redesigning, the existing G8 components:

- `RecentContextWindow`: at most 6 newest messages and at most 1200 tokens;
  newest-first selection with oldest eviction; no summarization or reorder;
- `OpenAICompatibleConversationQueryResolver`: at most one standalone-query
  provider call for non-empty bounded history, temperature `0`, max output
  `160`, retry `0`;
- expected provider/response failures return the original question as a safe
  fallback; unknown programming errors propagate;
- `EngineeringContextSnapshot` is the trusted internal handoff. Message
  content is excluded from its `repr` and is not emitted to safe Trace or
  Rich Activity.

`None`, `()`, and `[]` are legal no-history inputs and do not call the context
provider. Invalid history/message values fail through the existing strict
validation rather than being silently discarded.

## 3. Target Architecture

The target is one **Unified Engineering Agent Runtime** with one control state
and one logical budget owner:

```text
Unified Engineering Agent Runtime
├── Context Resolver
├── Evidence Planner
├── Execution Policy
├── Tool Execution Engine
├── Evidence Aggregator
├── Evidence Verifier
├── Finalization Policy
└── Activity / Observability
```

The intended logical sequence is:

```text
request
  -> Context Resolver
  -> Evidence Planner
  -> Execution Policy
  -> Tool Execution Engine
  -> Evidence Aggregator
  -> Evidence Verifier
  -> Finalization Policy
  -> Activity / Observability projection
```

The sequence is a control-plane decomposition, not permission to create nested
controllers. A component may expose a narrow interface, but only the Unified
Runtime owns the trusted run state and terminal transition.

### 3.1 Evidence backends

Knowledge RAG, Repository, Git, and Test capabilities are **Evidence
Backends**, not independent Agents. They provide bounded evidence through
ports/tools to the single Engineering Agent:

- Knowledge RAG: Dense, BM25, Hybrid, and Reranker retrieval over the shared
  knowledge corpus;
- Repository: lexical/symbol search and bounded project-context reads;
- Git: changed-files and diff evidence;
- Test: bounded test discovery and test-context evidence.

An Evidence Backend may not own planning, autonomous retries, a run budget,
finalization, or a competing stop/refusal state.

### 3.2 Context component boundary

`EngineeringContextResolver` has one responsibility:

```text
user_input + conversation_context
  -> RecentContextWindow.prepare
  -> optional single standalone resolution
  -> EngineeringContextSnapshot
```

It does not call a Planner, Retriever, ToolAgent, Verifier, or Finalizer. Its
provider call is not a ToolAgent iteration, Tool call, Tool error, or second
budget. Only `resolved_input` crosses into the requirement route and the
execution adapter.

## 4. Capability Migration Matrix

| Capability | Source | Current state | Target owner | Migration action | Compatibility requirement |
|---|---|---|---|---|---|
| G1/G2 Dense / BM25 / Hybrid / Reranker | `core/retriever/`, Gate 2 frozen artifacts | Existing Knowledge RAG strategies; historical metrics frozen | Evidence Backend + Evidence Aggregator | Wrap behind a retrieval Evidence Backend port; migrate one strategy at a time | Gate 2 corpus, config identity, ranking semantics, and frozen results unchanged |
| G3 `QueryPlan` | `core/query_planning/`, Gate 3 contracts | Implemented and historically validated; not on Engineering main chain | Evidence Planner | Adapt the frozen schema into the Planner component; do not copy AgentRuntime | Gate 3 plan schema/IDs and sealed/formal facts unchanged |
| Query Decomposition | G3 planner components | Available as a G3 capability; not active in current Engineering path | Evidence Planner | Migrate as Planner output bounded by the existing G3 limits | No new unbounded subquery loop; G3 limits remain regression constraints |
| Adaptive Router | `core/adaptive_retrieval/` | Existing G3 component; not current Engineering controller | Evidence Planner / Execution Policy boundary | Expose route decisions as data consumed by the single policy owner | Do not re-tune sealed Gate 3 routing facts during migration |
| Multi-query Retrieval | G3 retrieval orchestration | Historical capability, currently isolated | Evidence Backend orchestration under Execution Policy | Move calls behind the single policy-controlled execution path | One logical retrieval budget; no backend-owned retries or loop |
| Evidence Merge | G3 evidence components | Existing deterministic merge contract, not current ToolAgent evidence path | Evidence Aggregator | Adapt merged evidence to Unified Evidence schema | Preserve deterministic order, deduplication, and bounded output |
| `MinimalEvidenceVerifier` | G3 verifier implementation | Existing verifier, not current Engineering verifier owner | Evidence Verifier | Adapt as a verifier component, then reconcile with G12 Guard | Historical verifier behavior remains regression-only until VERIFY stage |
| Grounded Generation | Agentic RAG answer path / generator ports | Existing generation path; not a separate controller | Finalization Policy | Consume verified evidence through a single finalization transition | Existing generator failure semantics and safe failure categories preserved |
| Citation Validator | G3/G12 evidence/citation validation work | Partial/contract-specific validation exists | Evidence Verifier | Consolidate validation inputs under one verifier contract | No UI/persistence expansion; invalid citations never become trusted evidence |
| G4 Tool loop / allowlist / budget | `core/tool_agent/runtime.py`, `integration.py` | Active bounded ToolAgent execution: 5/4/2, allowlist, duplicate/error guards | Execution Policy + Tool Execution Engine | Keep ToolAgentRuntime as an execution component through the migration adapter | 5/4/2 hard enforcement, allowlist, and terminal semantics remain frozen |
| Safe Trace | `core/tool_agent/runtime_models.py`, `api/app.py` | Active safe projection; no raw prompt/observation/secret | Activity / Observability | Keep as an output projection of trusted events | Observability cannot change runtime outcomes or become control state |
| G6 Repository Evidence | `core/tool_agent/tools/`, repository adapters | Active read-only code/project evidence | Evidence Backend | Expose repo tools through Tool Execution Engine and Unified Evidence | Workspace binding, bounded output, path safety, and legacy endpoint regression |
| G8 Context / Standalone Resolver | `core/conversation_context/`, `core/engineering_context.py` | G8 result is `MIXED / USEFUL BUT NOT GENERAL`; component now fronts Engineering Runtime | Context Resolver | Reuse bounded window/resolver; pass one resolved input downstream | None/empty no provider; max one resolver call; fallback and fail-fast semantics preserved |
| G9 failure semantics | `core/generator/errors.py`, Agent/Tool runtime handling | Typed provider failures and programming-error propagation are active | Execution Policy + Finalization Policy | Map component failures into the single trusted run state | Provider text/key/traceback not leaked; unknown programming errors remain visible to boundary |
| G10 `changed_files` / `git_diff` / `find_tests` | `core/tool_agent/tools/` | Active read-only tools and workflow evidence | Evidence Backend + Evidence Aggregator | Register each as typed evidence producer under one execution policy | Existing safe path, diff bounds, candidate-source and endpoint contracts regress |
| G11 Unified Evidence | G11 Engineering response/runtime models | **ACTIVE**; current ToolAgent already emits several evidence kinds | Evidence Aggregator | Make all backend outputs conform to one evidence envelope and provenance path | G11 historical task-family outcomes and known negatives remain unchanged |
| G12 Typed Requirement / Finalization Guard | `core/engineering_requirements.py`, ToolAgent finalization guard | **ACTIVE**; requirement route and shape guard are integrated in current path | Execution Policy / Finalization Policy | Keep one requirement state and one finalization transition; later reconcile verifier | G12 question-only contract, guard schema, Formal and valid FAIL remain frozen |
| Rich Activity | `core/tool_agent/activity.py`, stream v2 | Active safe lifecycle projection | Activity / Observability | Project Unified Runtime events without feeding them back into control | No context content, prompt, raw observation, or outcome mutation |

## 5. Ownership Matrix

Every concern has one logical owner. Components may implement a delegated
operation, but they must not create a second authority for the same state.

| Concern | Unique owner | Owns | Explicitly does not own |
|---|---|---|---|
| Context | Context Resolver | bounded history selection, one optional standalone resolution, context snapshot | planning, retrieval, Tool loop, budget, finalization |
| Plan | Evidence Planner | normalized QueryPlan and bounded evidence intent | Tool execution, budget, final answer |
| Budget | Execution Policy | the one trusted run budget and stop decision | provider prompt suggestions, backend-local ledgers, observer counters |
| Evidence | Evidence Aggregator | evidence identity, provenance, deduplication, bounded merge | planning, finalization, UI decisions |
| Verification | Evidence Verifier | evidence sufficiency/shape/citation verification result | Tool retries, generation, public transport |
| Finalization | Finalization Policy | one terminal completed/refused/failed transition and answer eligibility | new evidence retrieval, observability delivery |
| Activity / Observability | Activity / Observability | safe trace/activity projection | any runtime decision, budget mutation, recovery, or outcome rewrite |

There is exactly **one logical Budget Owner**: `Execution Policy`. During
migration `ToolAgentRuntime` may continue to perform the existing 5/4/2 hard
enforcement because it is the current execution component. That does not make
it a second Agent or controller. Its budget checks must eventually be
represented as the Unified Runtime's execution-policy state, not duplicated by
an outer AgentRuntime.

Likewise, `AgentRuntime` must not wrap `ToolAgentRuntime`. Such nesting would
create two autonomous loops, two stop decisions, two ledgers, and ambiguous
ownership of evidence and finalization.

## 6. Compatibility contract

- Gate 1 through G12 frozen facts are not rewritten. Historical experiments,
  sealed/formal identities, metrics, negative results, and known limitations
  remain historical facts.
- Gate 2 and Gate 3 sealed/formal work is not re-tuned or re-run because of
  component migration.
- Legacy `/agent/query` and `/tool-agent/query` endpoints, plus the Engineering
  query and stream endpoints, retain regression coverage during migration.
- The G12 question-only contract remains: public Engineering requests expose
  only `{"question": "..."}`; history/context/messages/memory/session fields
  are not public API inputs.
- The current Engineering endpoints pass `conversation_context=None`. Future
  internal callers may use the component seam, but public API expansion is a
  separate decision.
- Context failures have a narrow contract: expected provider/response failure
  falls back to the original input and continues; unknown programming errors
  propagate; neither is classified as a Tool failure.
- Context resolution does not increment ToolAgent iterations, Tool calls, Tool
  errors, or the 5/4/2 budget.
- Migration is component-by-component with adapters and contract tests. It is
  not a big-bang rewrite and it does not permanently discard G3.
- No Persistence, Citation UI, new Multi-Agent design, or third product
  Runtime is implied by this document.

## 7. Current vs Target Architecture

### 7.1 Current capability islands

```text
                         current Engineering product path
Client ──> Facade ──> Unified Runtime ──> Adapter ──> ToolAgentRuntime
                                  route once             │
                                                         ├─ Decision
                                                         ├─ Tool allowlist
                                                         ├─ 5/4/2 hard budget
                                                         ├─ Observation
                                                         └─ G12 finalization guard

  G3 island (not current main chain)                 G8 legacy island
  ┌───────────────────────────────┐                 ┌──────────────────────┐
  │ Planner / QueryPlan            │                 │ RecentContextWindow  │
  │ Decomposition / Adaptive      │                 │ Standalone Resolver  │
  │ Multi-query / Merge / Verifier│                 │ historical Agent path│
  └───────────────────────────────┘                 └──────────────────────┘

  G11 Unified Evidence + G12 Requirement/Guard = active inputs, not yet one
  end-to-end Context → Plan → Policy → Evidence → Verify → Finalization plane.
```

### 7.2 Final unified control plane

```text
                  Unified Engineering Agent Runtime
┌──────────────────────────────────────────────────────────────┐
│ one trusted control state / one terminal transition            │
│                                                              │
│ Context Resolver → Evidence Planner → Execution Policy       │
│                                      │                       │
│                                      v                       │
│                         Tool Execution Engine                │
│                         /       |        \                  │
│                    Knowledge  Repo     Git/Test             │
│                         \       |        /                  │
│                          Evidence Aggregator                 │
│                                   │                          │
│                                   v                          │
│                         Evidence Verifier                    │
│                                   │                          │
│                                   v                          │
│                         Finalization Policy                  │
│                                   │                          │
│                                   v                          │
│                       Activity / Observability               │
└──────────────────────────────────────────────────────────────┘

Knowledge RAG / Repository / Git / Test are Evidence Backends. None is an
Agent, controller, budget owner, or finalizer.
```

## 8. Migration sequence

The only approved sequence is:

```text
ARCH-RUNTIME-02
→ ARCH-CONTEXT-03
→ ARCH-PLAN-04
→ ARCH-RETRIEVAL-05
→ ARCH-VERIFY-06
→ ARCH-CUTOVER-07
→ ARCH-EVAL-08
→ Productization
```

Each stage must leave a reviewable boundary, preserve the compatibility
contract, and stop after its own acceptance. No stage may introduce a nested
autonomous controller or a third product Runtime.
