# Unified Runtime Evidence Planning Migration

> Task: `ARCH-PLAN-04`
> Date: 2026-08-31
> Status: **CURRENT**

## 1. Planner solves what problem?

An Engineering question can be a simple fact, a comparison, a code-symbol
question, or a multi-entity evidence task. The Planner turns the resolved
question into a small, inspectable evidence intent: whether retrieval is
needed, what query type it has, and whether the evidence intent should be
decomposed. This makes planning auditable without letting the model choose
runtime budgets or execute tools.

## 2. What is QueryPlan?

`QueryPlan` is the existing immutable G3 schema. It contains the normalized
original query, query type, retrieval-required flag, action, reason code, an
optional ordered tuple of `Subquery` values, fallback policy, and a stable
`plan_id` derived from the canonical identity payload. `PlannerOutcome` wraps
that plan with `fallback_used`, `failure_code`, and optional bounded call
metadata.

ARCH-PLAN-04 reuses `core/query_planning/models.py`, `planner.py`,
`openai_compatible.py`, and `prompt.py`. It does not create an
`EngineeringQueryPlan`, `EngineeringSubquery`, or a second fallback factory.

## 3. Query Decomposition is not Multi-Agent

Decomposition produces multiple evidence questions inside one run. It does
not create identities, prompts, memory, budgets, or controllers for multiple
Agents. One Unified Engineering Agent still owns the run. Subqueries are
trusted planning data; retrieval execution remains a later policy decision.

## 4. Planner versus Router

The Planner answers “how should the evidence intent be organized?” and emits a
`QueryPlan`. The Requirement Router answers “what evidence obligation applies
to this resolved input?” and emits the existing typed requirement. They are
different responsibilities and are called once in this order:

```text
Context Resolver → Evidence Planner → Requirement Router → execution adapter
```

The Planner does not select `knowledge_search`, BM25, Hybrid, top-k, or a
retrieval round. Those choices belong to later Execution Policy / Retrieval
migration.

## 5. Planner versus ToolAgent Decision

The Planner produces a trusted, pre-execution evidence intent. The
ToolAgent Decision provider chooses the next bounded ToolAgent action from the
registered Tool contract and current observations. The former does not execute
anything; the latter remains inside the existing Decision → Tool → Observation
loop.

Both receive the same `resolved_input`, but the PlannerOutcome is not inserted
into the ToolAgent prompt or used to force a Tool choice in this stage.

## 6. Why at most three subqueries?

G3 freezes a small upper bound of three subqueries to keep decomposition
bounded, auditable, and comparable. A decomposed plan must contain two or
three ordered `sq1`/`sq2`/`sq3` entries. Zero or one is under-decomposition;
four or more is over-decomposition. The bound prevents the model from turning
planning into an unbounded retrieval loop.

## 7. Why strict schema?

The model is not trusted to define identity or control state. Strict parsing
rejects unknown fields, duplicate JSON keys, invalid types, invalid enum
combinations, duplicate subqueries, and invalid cardinality. `plan_id` is
recomputed from the canonical payload, so a model cannot forge identity or
declare `PLANNER_FALLBACK` as if it were a normal plan.

## 8. Why deterministic fallback?

Malformed output, empty output, over/under-decomposition, duplicate subqueries,
timeout, and known provider failures produce the existing system-owned
`PlannerOutcome` fallback: `single_retrieval` over the original query with
`reason_code=PLANNER_FALLBACK`. This keeps the Engineering run usable without
letting malformed model output become an execution policy.

The fallback is not an Agent failure, Tool failure, Tool error, final refusal,
or extra ToolAgent counter. It also does not trigger a second planning call.

## 9. Why programming bugs must propagate

The G3 boundary catches only explicitly classified provider/response failures.
An unexpected `RuntimeError` or other programming defect propagates before
Requirement routing and Tool execution. Catching every exception would hide
implementation defects as normal provider degradation and make the system
harder to audit.

## 10. Why this stage forms Plan but does not execute Multi-query Retrieval

ARCH-PLAN-04 deliberately ends at a trusted `PlannerOutcome`. It does not use
`plan.action`, `plan.query_type`, `plan.subqueries`, or
`plan.retrieval_required` to change Tool selection, strategy, top-k, subquery
loops, evidence merge, adaptive rescue, or G12 finalization. Plan enforcement
is **DEFERRED TO ARCH-RETRIEVAL-05**.

This makes the migration seam testable: a legal single-retrieval plan and a
legal decomposed plan produce the same scripted ToolAgent result in this
stage, with no additional Tool calls or loop iterations.

## 11. Avoiding a nested AgentRuntime

The Planner is a component with one method and one bounded delegation. It does
not call the old `core.agent_runtime.AgentRuntime`, and it does not wrap
`ToolAgentRuntime`. The resulting shape is:

```text
UnifiedEngineeringRuntime
├── Context Resolver
├── Evidence Planner
└── Legacy Tool execution component
```

There is still one trusted control state, one logical budget owner, and one
ToolAgent loop. G3 capabilities can therefore migrate without becoming a
second product Runtime.

## 12. Why the Planner provider call is not a Tool call

The Planner provider call produces control metadata before Tool execution. It
does not invoke a registered Tool, consume an observation, or advance the
ToolAgent Decision → Tool → Observation loop. It therefore does not increment
`iterations_used`, `tool_calls_used`, or `tool_errors_used`, and it does not
create a second planner budget. ToolAgent's frozen 5/4/2 enforcement remains
unchanged.

The production Planner reuses the Engineering provider identity
`deepseek/deepseek-chat`, `DEEPSEEK_BASE_URL`, and `DEEPSEEK_API_KEY`, but its
messages and identity remain the existing G3 Planner prompt/version from
`core/query_planning/prompt.py`, not the ToolAgent decision prompt.

## 13. Two-minute interview explanation

“I migrated G3 planning as a component, not as another Agent. The existing
strict `QueryPlan` and `PlannerOutcome` remain the source of truth. The Unified
Runtime first resolves context, then calls one Evidence Planner on the
resolved query, then routes the same query and delegates to the existing
ToolAgent loop. A plan can be single or decomposed, but in this stage it is
only trusted planning state: it does not choose tools or run subqueries.
Malformed/provider failures use G3's deterministic single-retrieval fallback;
unknown programming bugs propagate. This preserves the 5/4/2 ToolAgent
budget, avoids nested AgentRuntime controllers, and leaves multi-query
retrieval enforcement for ARCH-RETRIEVAL-05.”

## 14. Common design mistakes

- Rebuilding `QueryPlan` or `Subquery` under an Engineering-specific schema.
- Calling Planner on the original query while Context, Router, or ToolAgent use
  the resolved query.
- Calling Planner more than once or adding a Planner retry loop.
- Treating decomposition as permission to create Multi-Agent workers.
- Letting the plan choose Tool names, retrieval strategy, top-k, or loop count
  before ARCH-RETRIEVAL-05.
- Counting the Planner provider call as a ToolAgent iteration or Tool error.
- Converting an unknown programming bug into deterministic fallback.
- Exposing QueryPlan, raw planner JSON, prompt text, or subqueries in API,
  Trace, Activity, or SSE.
- Reusing `build_pipeline_agent_runtime`, which would bring back the old
  AgentRuntime controller.
- Copying Gate 3's AgentRuntime instead of migrating its components.
- Tuning or rewriting Gate 3 sealed/formal facts during this migration.
