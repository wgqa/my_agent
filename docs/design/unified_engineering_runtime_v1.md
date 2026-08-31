# Unified Engineering Runtime v1

> Status: **Architecture baseline and migration contract**
> Project identity: **Evidence-Grounded AI Engineering Agent**
> Architecture baseline: `c6ee568923babcb0dc3e040ceef1e18e162b02db`
> Current migration baseline: `c08cdb0886ee3e3dc1e89c9bdeaa7117ae90deab`
> Current migration: `ARCH-VERIFY-06`
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
  historically evaluated, but were not in this Engineering main chain at the
  architecture-freeze starting point.
- At the ARCH-CONTEXT-03 starting baseline, G8 Context / Standalone Resolver
  was also not in the Engineering main chain. Its historical integration in
  `core/agent_runtime/runtime.py` remains a legacy path and is not rewritten.
- G11 Unified Evidence and G12 Typed Requirement / Finalization Guard are
  **ACTIVE** integration inputs. They do not imply that every historical
  component has already been migrated.
- `P1-OBS-03A-R1-MICRO` is **ACCEPT / CLOSED**. Safe Trace and Rich Activity
  are observational projections and cannot decide or mutate a run outcome.

### 2.2 Migration state after ARCH-PLAN-04

ARCH-CONTEXT-03 added the Context component. ARCH-PLAN-04 adds the G3
Evidence Planner component and makes the current migration chain:

```text
request
  -> EngineeringContextResolver
  -> EngineeringContextSnapshot.resolved_input
  -> EngineeringEvidencePlanner.plan(resolved_input) exactly once
  -> trusted PlannerOutcome / QueryPlan (passive in this stage)
  -> requirement route exactly once
  -> LegacyToolAgentExecutionAdapter
  -> ToolAgentRuntime's existing 5/4/2 execution loop
```

`Planner = ACTIVE` means that a trusted G3 `PlannerOutcome` is formed exactly
once. `Plan enforcement = NOT YET ACTIVE` and is deferred to
`ARCH-RETRIEVAL-05`: this stage does not use `action`, `query_type`,
`subqueries`, or `retrieval_required` to select Tools, change retrieval
strategy/top-k, loop over subqueries, merge evidence, rescue Hybrid, or alter
G12 finalization. ToolAgentRuntime still owns the execution loop during
migration; the Context and Planner components are not Agents and do not add a
loop, budget ledger, finalization decision, or Tool call.

### 2.3 Migration state after ARCH-RETRIEVAL-05

ARCH-RETRIEVAL-05 makes the trusted Plan executable only for the bounded Knowledge
Retrieval component. The current migration chain is:

```text
resolved_input
  -> Evidence Planner -> trusted PlannerOutcome / QueryPlan
  -> Requirement Router
  -> EngineeringRetrievalComponent
       -> Adaptive route decision
       -> single or exact QueryPlan subquery execution
       -> optional one Hybrid rescue
       -> deterministic RRF merge v2 / EvidenceBundle
  -> planned evidence handoff
  -> LegacyToolAgentExecutionAdapter
  -> ToolAgentRuntime (filtered registry, existing 5/4/2 loop)
```

The retrieval component is a finite policy execution component, not an Agent and
not a second controller. It reuses the existing G3 `DeterministicRouter`,
`RetrievalPort`, `EvidenceBundle`, `merge_subquery_results_policy`,
`SUBQUERY_RRF_MERGE_V2`, and `DEFAULT_MERGE_RRF_K`. The frozen contract is:

- `no_retrieval`: zero retrieval-port calls and an empty G3 `EvidenceBundle`;
- `single`: one primary call, with at most one Hybrid rescue after an empty BM25
  result, for at most two calls total;
- `decomposed`: exactly the existing two or three QueryPlan subqueries, primary
  BM25 in plan order, and at most one Hybrid rescue for the first missing
  subquery, for at most four calls total;
- `top_k = 5`, `max_retrieval_calls = 4`, `merge_policy =
  subquery_rrf_merge_v2`, and `merge_rrf_k = 60.0` remain frozen.

The internal G3 `EvidenceBundle`, `query_id`, retrieval-call count, and query
count remain trusted state. Only its bounded, safe `KnowledgeEvidence` conversion
and `DecisionContextItem` projection are handed to ToolAgent. The Engineering
run disables the second `knowledge_search` Tool; the legacy `/tool-agent/query`
path keeps its existing registry and behavior. Retrieval calls do not inflate
ToolAgent `iterations_used`, `tool_calls_used`, or `tool_errors_used`; unified
budget reconciliation remains a later cutover concern.

ARCH-RETRIEVAL-05 does not migrate `MinimalEvidenceVerifier`, Grounded
Generation, Finalization Policy, or Citation Validator. ToolAgentRuntime remains
the only LLM Decision → Tool → Observation loop, and no nested autonomous
controller or replanning/retry loop is introduced.

### 2.4 Migration state after ARCH-VERIFY-06

ARCH-VERIFY-06 reconciles the planned retrieval result, G3's existing
`MinimalEvidenceVerifier`, G12's typed requirement evaluator, and the existing
`CitationValidator` behind one `EngineeringEvidenceVerifier`. The current
Engineering chain is now:

```text
Context Resolver
  -> Evidence Planner -> Requirement Router
  -> Planned Knowledge Retrieval / Evidence Aggregator
  -> ToolAgentRuntime dynamic Repo/Git/Test evidence
  -> EngineeringEvidenceVerifier
       -> one EngineeringVerificationResult
       -> one can_finalize decision
  -> existing ToolAgent finalization point
```

The verifier delegates existing checks; it does not replace their algorithms,
claim-level semantics, prompts, or frozen artifacts. `MinimalEvidenceVerifier`
is a query-level retrieval/coverage check, G12 remains a typed evidence-shape
check, and `CitationValidator` checks citation-ID existence only. No component
claims semantic entailment or LLM-judge grounding. A citation-free answer is
nonblocking; an invalid citation reference is blocking.

Coverage truth is recorded in `EngineeringRetrievalSnapshot` before
deterministic RRF merge: direct retrieval has no required query IDs, single
retrieval uses `q0`, and decomposition uses the exact ordered `sq1`… IDs.
RRF's representative item query ID is never used as a substitute for this
pre-merge coverage truth. Retrieval insufficiency or incomplete subquery
coverage is a non-recoverable hard stop; G12 missing Repository/Git/Test
evidence may use the next existing ToolAgent Decision when the producer and
the frozen 5/4/2 budget permit it. Planned Knowledge Retrieval is not rerun.

The unified result is the only verification input to the existing finalization
point on this path. `ToolAgentRuntime` still enforces 5/4/2 and executes the
bounded loop, but it is only the Unified Runtime's execution component; there
is no FinalizationRuntime, nested AgentRuntime, repair LLM, or new controller.

### 2.5 G8 context contract being migrated

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

### 2.6 Planner component contract

`EngineeringEvidencePlanner` accepts only an existing `BaseQueryPlanner` and
returns the exact existing `PlannerOutcome` object after strict type and
resolved-query identity validation. It does not reconstruct `QueryPlan`,
`Subquery`, fallback plans, parser behavior, or prompt identity. The wrapped
G3 planner remains responsible for its one provider call, strict schema,
deterministic fallback, and programming-error propagation.

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
| G3 `QueryPlan` | `core/query_planning/`, Gate 3 contracts | **ACTIVE** as trusted Planner state and the input to bounded Knowledge Retrieval | Evidence Planner | Adapt the frozen schema through `EngineeringEvidencePlanner`; do not copy AgentRuntime | Gate 3 plan schema/IDs and sealed/formal facts unchanged |
| Query Decomposition | G3 planner components | **ACTIVE** as a 2/3-subquery Planner output consumed by planned retrieval | Evidence Planner + Execution Policy boundary | Preserve the existing bounded output; execute only its exact subqueries through the retrieval component | No dynamic subquery or unbounded loop; G3 limits remain regression constraints |
| Adaptive Router | `core/adaptive_retrieval/` | **ACTIVE in ARCH-RETRIEVAL-05** as a bounded route decision; not an autonomous controller | Execution Policy via `EngineeringRetrievalComponent` | Reuse the pure G3 route decision and execute only the frozen single/decomposed policy | Do not re-tune sealed Gate 3 routing facts; no new retrieval budget |
| Multi-query Retrieval | G3 retrieval orchestration and `core/engineering_retrieval.py` | **ACTIVE in ARCH-RETRIEVAL-05** behind the planned retrieval handoff | Execution Policy + Knowledge Evidence Backend | Execute the exact QueryPlan subqueries, at most one rescue, and no new subquery/loop | 2–3 primary calls, at most one Hybrid rescue, total ≤4; legacy path regresses |
| Evidence Merge | `core/agent_runtime/evidence.py`, `core/engineering_retrieval.py` | **ACTIVE in ARCH-RETRIEVAL-05** as deterministic internal G3 `EvidenceBundle` merge | Evidence Aggregator | Reuse `merge_subquery_results_policy` with frozen RRF merge v2 and convert only bounded public evidence | Preserve query IDs, provenance, deduplication, deterministic order, max 5, and RRF k=60 |
| `MinimalEvidenceVerifier` | G3 verifier implementation | **ACTIVE in ARCH-VERIFY-06** as a delegated query-level retrieval/coverage check | Evidence Verifier | Call the existing verifier with snapshot pre-merge required/covered IDs and retain its `VerificationResult` | No algorithm, semantic claim, threshold, or frozen artifact change |
| Grounded Generation | Agentic RAG answer path / generator ports | Existing generation path; answer eligibility now consumes the unified result, but semantic grounding is not claimed | Finalization Policy | Pass the proposed answer through the one verification seam before the existing finalization transition | Existing generator failure semantics preserved; no LLM judge or semantic entailment claim |
| Citation Validator | `core/generator/citation.py` | **ACTIVE in ARCH-VERIFY-06** as citation-ID existence checking | Evidence Verifier | Adapt the same EvidenceBundle items to ContextBlock and delegate one citation check | Citation-free answer is nonblocking; invalid IDs block; no UI/persistence expansion |
| G4 Tool loop / allowlist / budget | `core/tool_agent/runtime.py`, `integration.py` | Active bounded ToolAgent execution: 5/4/2, allowlist, duplicate/error guards; Engineering can receive seeded evidence and a filtered registry | Execution Policy + Tool Execution Engine | Keep ToolAgentRuntime as the execution component through the migration adapter; disable duplicate Engineering knowledge search | 5/4/2 hard enforcement, allowlist, and terminal semantics remain frozen; legacy registry unchanged |
| Safe Trace | `core/tool_agent/runtime_models.py`, `api/app.py` | Active safe projection; no raw prompt/observation/secret | Activity / Observability | Keep as an output projection of trusted events | Observability cannot change runtime outcomes or become control state |
| G6 Repository Evidence | `core/tool_agent/tools/`, repository adapters | Active read-only code/project evidence | Evidence Backend | Expose repo tools through Tool Execution Engine and Unified Evidence | Workspace binding, bounded output, path safety, and legacy endpoint regression |
| G8 Context / Standalone Resolver | `core/conversation_context/`, `core/engineering_context.py` | G8 result is `MIXED / USEFUL BUT NOT GENERAL`; Context component fronts Engineering Runtime | Context Resolver | Reuse bounded window/resolver; pass one resolved input downstream | None/empty no provider; max one resolver call; fallback and fail-fast semantics preserved |
| G9 failure semantics | `core/generator/errors.py`, Agent/Tool runtime handling | Typed provider failures and programming-error propagation are active | Execution Policy + Finalization Policy | Map component failures into the single trusted run state | Provider text/key/traceback not leaked; unknown programming errors remain visible to boundary |
| G10 `changed_files` / `git_diff` / `find_tests` | `core/tool_agent/tools/` | Active read-only tools and workflow evidence | Evidence Backend + Evidence Aggregator | Register each as typed evidence producer under one execution policy | Existing safe path, diff bounds, candidate-source and endpoint contracts regress |
| G11 Unified Evidence | G11 Engineering response/runtime models | **ACTIVE**; Retrieval now hands off trusted planned Knowledge evidence while ToolAgent emits other evidence kinds | Evidence Aggregator | Preserve internal G3 bundle identity and adapt backend outputs to one evidence envelope/provenance path | G11 historical task-family outcomes and known negatives remain unchanged |
| G12 Typed Requirement / Finalization Guard | `core/engineering_requirements.py`, ToolAgent finalization guard | **ACTIVE**; typed requirement is delegated into the unified result and existing finalization point remains the seam | Evidence Verifier + Finalization Policy | Reuse one G12 state in `EngineeringVerificationResult`; allow only bounded producer-tool recovery | G12 question-only contract, guard schema, Formal and valid FAIL remain frozen |
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
| Verification | Evidence Verifier | one `EngineeringVerificationResult` composed from G3 retrieval coverage, G12 evidence shape, and citation-ID checks | Tool retries, generation, semantic entailment claims, public transport |
| Finalization | Finalization Policy | one terminal completed/refused/failed transition, consuming the unified `can_finalize` result and bounded recovery fields | independent G3/G12/Citation decisions, new evidence retrieval, observability delivery |
| Activity / Observability | Activity / Observability | safe trace/activity projection | any runtime decision, budget mutation, recovery, or outcome rewrite |

There is exactly **one logical Budget Owner**: `Execution Policy`. During
migration `ToolAgentRuntime` may continue to perform the existing 5/4/2 hard
enforcement because it is the current execution component. That does not make
it a second Agent or controller. Its budget checks must eventually be
represented as the Unified Runtime's execution-policy state, not duplicated by
an outer AgentRuntime.

The verifier is also one logical verification owner: G3
`MinimalEvidenceVerifier`, G12 `evaluate_evidence_requirement`, and
`CitationValidator` are delegated checks, not three competing finalizers. The
existing ToolAgent finalization branch consumes the one result; it does not
independently recompute G12 when the unified seam is enabled.

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
- ARCH-RETRIEVAL-05 uses the frozen retrieval contract only:
  `adaptive_retrieval_policy_v1`, `top_k=5`, `max_retrieval_calls=4`,
  `subquery_rrf_merge_v2`, and `merge_rrf_k=60.0`. Single retrieval is one
  primary plus at most one Hybrid rescue; decomposed retrieval is two or three
  primary subqueries plus at most one rescue. There is no new
  `RetrievalBudget` or autonomous retrieval loop.
- The trusted internal G3 `EvidenceBundle` retains `query_id`, retrieval-call
  count, and query count. Public conversion is fail-closed for unsafe
  provenance and emits only bounded `KnowledgeEvidence` plus bounded
  `DecisionContextItem` seed data.
- Planned evidence is handed to the existing ToolAgent run before its first
  Decision. The Engineering registry disables the duplicate `knowledge_search`
  Tool, while the legacy `/tool-agent/query` registry and behavior remain
  unchanged. Retrieval calls do not increment ToolAgent counters.
- ARCH-VERIFY-06 reuses the existing G3 `MinimalEvidenceVerifier`, G12 typed
  evaluator, and `CitationValidator` behind one `EngineeringEvidenceVerifier`
  and one `EngineeringVerificationResult`. The result's `can_finalize` is the
  conjunction of retrieval sufficiency, G12 requirement satisfaction, and
  non-invalid citation status. It does not claim semantic entailment.
- Required/covered subquery IDs come from pre-merge retrieval results, not the
  representative query ID on a deduplicated RRF item. Missing G12
  Repository/Git/Test evidence may recover through an existing producer Tool
  within 5/4/2; retrieval insufficiency, incomplete planned coverage, and
  invalid citation references hard-stop with the existing public refusal code.
- `CitationValidator` is nonblocking when the answer has no citations. No
  citation repair LLM, knowledge-search retry, or additional finalizer is
  introduced, and verification does not change ToolAgent counters.
- The current `ToolAgentRuntime` enforcement remains the only 5/4/2 hard
  enforcement during migration; the Unified Runtime still has exactly one
  logical Budget Owner. ToolAgentRuntime is an execution component, not a
  second Agent/controller.
- Migration is component-by-component with adapters and contract tests. It is
  not a big-bang rewrite and it does not permanently discard G3.
- No Persistence, Citation UI, new Multi-Agent design, or third product
  Runtime is implied by this document.

## 7. Current vs Target Architecture

### 7.1 Current capability islands

```text
                         current Engineering product path
Client ──> Facade ──> Unified Runtime
                         │
                         ├─ Context Resolver
                         ├─ Evidence Planner (trusted QueryPlan)
                         ├─ Requirement route once
                         ├─ Planned Knowledge Retrieval
                         │    └─ Adaptive / multi-query / RRF v2 → EvidenceBundle
                         └─ Adapter ──> ToolAgentRuntime
                                               ├─ Decision
                                               ├─ Tool allowlist
                                               ├─ 5/4/2 hard budget
                                               ├─ Observation / Repo-Git-Test evidence
                                               └─ EngineeringEvidenceVerifier
                                                    ├─ G3 MinimalEvidenceVerifier
                                                    ├─ G12 typed requirement
                                                    ├─ Citation-ID validator
                                                    └─ one can_finalize result
                                                         │
                                                         v
                                                    existing finalization point

  Remaining integration drift (cutover is not yet complete)
  ┌────────────────────────────────────────────────────────┐
  │ Execution Policy ownership and Finalization Policy      │
  │ still converge through the ToolAgent execution adapter  │
  └────────────────────────────────────────────────────────┘

  G8 is now a Context component; G3 Planner/Decomposition, Adaptive Retrieval,
  Multi-query Retrieval, deterministic Evidence Merge, and unified verification
  are bounded components. G11 Unified Evidence and G12 Requirement/Guard
  remain active inputs; final control-plane cutover is the remaining drift.
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
