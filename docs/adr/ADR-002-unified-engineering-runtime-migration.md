# ADR-002: Unified Engineering Runtime Migration

> Status: **Accepted — architecture freeze; ARCH-CUTOVER-07 migration active**<br>
> Date: **2026-08-31**<br>
> Baseline: `0eef8ef9d6decdaa10efebe04087b06611654670`<br>
> Scope: Unified Runtime architecture and bounded G8/G3 Context, Planning, Knowledge Retrieval, and Evidence Verification component migration；不授权无关生产 Runtime 变更。

## Context

项目已经从 RAG、Gate 3 Planning/Adaptive Retrieval、Gate 4 Structured Tool Agent、G6 Repository Evidence、G8 Context、G9 Reliability、G10 Change/Test Evidence 演进到 G11 Unified Evidence 和 G12 Typed Requirement / Finalization Guard。

但当前 Engineering 产品入口的实际 LLM execution loop 仍是：

```text
EngineeringAgentFacade → ToolAgentRuntime → bounded Tool loop → finalization
```

ARCH-FREEZE-01 起点时，G3 的 Planner、Query Decomposition、Adaptive Retrieval、Multi-query Retrieval、`MinimalEvidenceVerifier` 与 G8 Context / Standalone Resolver 没有进入这条主链。ARCH-CONTEXT-03、ARCH-PLAN-04、ARCH-RETRIEVAL-05、ARCH-VERIFY-06 已分别把 Context、trusted Plan、有限 planned Knowledge Retrieval 与统一 Verification seam 接到迁移边界；但 ToolAgent 仍承载唯一的 Decision → Tool → Observation execution loop，最终的主链装配、fail-fast 组件契约与入口一致性仍需单独 cutover。G11/G12 已经形成统一 evidence 和 requirement/guard 的重要输入，现阶段的 **Architecture Integration Drift** 具体收敛为：能力已经有组件边界，但生产 Engineering assembly 仍必须明确唯一控制状态、唯一 budget owner、唯一 finalization seam，且不能通过兼容分支静默降级。

本 ADR 与以下事实同时成立：

- G1～G12 的历史 Gate/frozen/sealed/formal facts 只读，不因迁移改写；
- Gate 2 / Gate 3 sealed/formal 结果不重新调参或重跑；
- `P1-OBS-03A-R1-MICRO = ACCEPT / CLOSED`，observability 与 runtime outcomes 保持隔离；
- 当前 G11 Unified Evidence、G12 Requirement/Guard 是 **ACTIVE** 的架构整合输入；
- G12 question-only request contract 继续有效。

## Decision

采用 **Unified Engineering Agent Runtime v1**，决策如下：

1. **Single Engineering Agent**：产品只有一个 Engineering Agent，不向 Knowledge RAG、Repository、Git、Test backend 分配 Agent 身份。
2. **One trusted control state**：一次 run 只有一个控制状态和一个 completion transition，包含 Context、Plan、Policy/Budget、Evidence、Verification、Finalization 及 safe activity projection。
3. **One logical budget owner**：目标唯一 owner 是 `Execution Policy`。迁移期间 `ToolAgentRuntime` 可以继续执行 frozen `5/4/2` hard enforcement，但只是 Unified Runtime 的 execution component，不是第二个 controller。
4. **Component migration**：按 `ARCH-RUNTIME-02` → `ARCH-CONTEXT-03` → `ARCH-PLAN-04` → `ARCH-RETRIEVAL-05` → `ARCH-VERIFY-06` → `ARCH-CUTOVER-07` → `ARCH-EVAL-08` → `Productization` 逐步迁移。
5. **No nested autonomous controller**：禁止 `AgentRuntime` 套 `ToolAgentRuntime`，禁止两个自主 loop、两个 finalization、两个 budget ledger 或两个互相竞争的 stop/refusal 机制。
6. **No third product Runtime**：既不复制 Gate 3 `AgentRuntime` 成为另一套产品 runtime，也不在现有 ToolAgentRuntime 外再发明第三个产品 Runtime。
7. G3 能力**不被永久废弃**：QueryPlan、decomposition、adaptive retrieval、multi-query merge 和 verifier 作为已验证 component，通过 adapter 和统一 contract 进入目标控制面。

## Why G11 ToolAgent-only was reasonable but temporary

G11 阶段选择 ToolAgent-only 是合理的工程简化，原因是：

- G11 首先要验证跨任务族的 Engineering evidence、tool safety、bounded loop、failure semantics 和 transfer-validation，而不是在同一轮同时重组所有历史 Runtime；
- G4 `ToolAgentRuntime` 已经提供明确的 allowlist、duplicate-call guard、`5/4/2` hard budget、structured action、safe trace 和 bounded termination，复用它可以降低新增 controller 的实验风险；
- G3 的 sealed/formal 边界已经冻结。把 G3 AgentRuntime 当作 G11 的新主链，会混入不同的 planner/retrieval/generator 假设，难以区分 G11 的 task evidence 与历史 G3 结果；
- ToolAgent-only 让 G11 能在不改写 Gate 2/3 frozen evidence 的前提下完成工程任务 transfer validation，并暴露 evidence sufficiency、bilateral grounding、premature finalization 等真正的系统性 debt。

这个决定的范围是“当时用于验证和交付的最小主链”，不是最终架构承诺。随着 G11/G12 暴露出能力整合 drift，继续把 ToolAgent-only 当成永久架构会把临时简化误当成设计真相，因此现在需要冻结迁移边界。

## Why we do not roll back or copy Gate 3 AgentRuntime

不回滚的原因：回滚会把已经形成的 G4/G6/G9/G10/G11/G12 product boundary、Tool Agent safety 和当前 Engineering endpoint 退回到较早的 runtime 假设；也会混淆已冻结的 Gate 3 历史事实与当前产品行为。历史正确不等于应当重新成为当前 controller。

不复制的原因：复制 Gate 3 `AgentRuntime` 会复制 QueryPlan、RouteDecision、EvidenceBundle、budget、finalization 和 trace 的权威来源，产生两套 schema 和两套行为。之后即使两个 runtime 都“可用”，也无法回答哪个 planner、哪个 verifier、哪个 budget ledger 对一次 Engineering run 负责。

正确的复用方式是把 G3 的已验证能力作为 component：保留 frozen contract 和 historical artifact，通过 adapter 接入 Unified Runtime 的 Context/Plan/Evidence/Verification owner。这样既不回滚，也不复制 controller。

## Why AgentRuntime must not wrap ToolAgentRuntime

`AgentRuntime → ToolAgentRuntime` 的嵌套会形成两个 controller：外层可能拥有自己的 plan/round/budget/finalization，内层又拥有 `5/4/2`、allowlist、duplicate guard 和 stop/refusal。其风险是结构性的：

- 一次 Tool call 到底由哪一层计入 budget 不再唯一，容易 double spend 或绕过 hard limit；
- 外层和内层可能分别决定继续、拒答、失败或 completed，最终状态没有单一真相；
- outer observation 与 inner observation 的 provenance、citation 和 evidence sufficiency 可能不一致；
- trace/activity 无法稳定表达真正的 step owner，异常恢复会变成递归或重复执行；
- backend 或 nested runtime 可能偷偷获得第二套 autonomous planning，破坏 Evidence Backend “不是 Agent”的边界。

因此 `ToolAgentRuntime` 在迁移期只能位于 `Tool Execution Engine` 这一侧，接受统一的 execution policy 并执行它。它不得再被描述为 Unified Runtime 之外的 Agent/controller。

## Why component migration instead of rewrite or permanently dropping G3

选择 component migration 是因为 G3 能力已经有明确模型、历史实验和 frozen/sealed 保护；QueryPlan、decomposition、adaptive retrieval、multi-query retrieval、merge 和 `MinimalEvidenceVerifier` 的价值不应因为当前未接线就被丢弃。永久废弃 G3 会直接放弃复杂问题覆盖、计划可审计性和 Evidence-first retrieval 的能力基础，不能解决 drift，只会把债务隐藏起来。

选择 component migration 而不是 rewrite，是因为 big-bang rewrite 会同时改变控制流、预算、retrieval、evidence、failure 和 endpoint compatibility，无法将新问题归因到单一迁移阶段，也更容易意外重写 Gate 3 结论。逐组件迁移可以：

- 先冻结唯一 owner 和 state boundary；
- 通过 adapter 复用已有实现，不复制自主控制器；
- 每阶段保持 legacy endpoint regression；
- 在 `ARCH-EVAL-08` 才评估 cutover 后的系统能力；
- 保留 G3 的历史事实，同时允许它以目标 component 形式重新进入产品主链。

## ARCH-CONTEXT-03 implementation addendum

ARCH-CONTEXT-03 applies this ADR to the first component migration without
changing the decisions above. The new `EngineeringContextResolver` reuses the
existing `RecentContextWindow` and
`OpenAICompatibleConversationQueryResolver`, and returns one trusted
`EngineeringContextSnapshot`. The Unified Runtime consumes only
`snapshot.resolved_input`, routes that input once, and passes the same value to
the ToolAgent execution adapter.

The migrated Context component has no autonomous loop, planner, retrieval
policy, finalization policy, or independent budget. `None`, `()`, and `[]` are
legal no-history inputs with zero context-provider calls. Non-empty history is
bounded to G8's six messages/1200 tokens and receives at most one standalone
resolution. Expected resolver failures safely fall back to the original input;
unknown programming errors propagate. The existing ToolAgentRuntime remains
the only 5/4/2 Decision → Tool → Observation loop during migration.

This addendum is a component migration, not a Gate re-evaluation: it does not
rewrite G8's `MIXED / USEFUL BUT NOT GENERAL` conclusion, change G12's
question-only contract, or authorize a second controller, a second logical
budget owner, a third product Runtime, Persistence, Citation UI, or Formal
reruns.

## ARCH-PLAN-04 implementation addendum

ARCH-PLAN-04 migrates only the G3 planning boundary. The new
`EngineeringEvidencePlanner` accepts an existing `BaseQueryPlanner`, delegates
one `plan(resolved_input)` call, validates the returned `PlannerOutcome` and
resolved-query identity, and returns the same existing outcome without
reconstructing `QueryPlan` or `Subquery`.

The Unified Runtime order is now Context → Evidence Planner → Requirement
Router → Legacy Tool execution. The Planner outcome is trusted planning state
but remains passive in this stage: it does not select Tools, change strategy or
top-k, execute subqueries, merge evidence, run adaptive rescue, or alter G12
finalization. Plan enforcement is deferred to ARCH-RETRIEVAL-05.

Production wiring uses the existing G3 `OpenAICompatibleQueryPlanner` and G3
Planner prompt with provider identity `deepseek/deepseek-chat`, existing
`DEEPSEEK_BASE_URL`, and `DEEPSEEK_API_KEY`. Planner provider calls are not
ToolAgent iterations, Tool calls, Tool errors, or a second budget ledger.
Unknown programming errors propagate before routing or execution; known G3
provider/output failures retain deterministic `single_retrieval` fallback.

## ARCH-RETRIEVAL-05 implementation addendum

ARCH-RETRIEVAL-05 migrates only the planned Knowledge Retrieval execution
boundary. `EngineeringRetrievalComponent` reuses the existing pure G3
`DeterministicRouter`, `RetrievalPort`, `EvidenceBundle`, and deterministic
`merge_subquery_results_policy` with frozen `SUBQUERY_RRF_MERGE_V2` and
`merge_rrf_k=60.0`; it does not instantiate or call the old G3 `AgentRuntime`.

The component is finite and policy-bound: `no_retrieval` makes zero port calls;
single retrieval makes one primary call and at most one Hybrid rescue; a
decomposed plan executes its exact two or three subqueries and allows at most
one rescue for the first missing subquery. `top_k=5` and total retrieval calls
`<=4` remain frozen. There is no new `RetrievalBudget`, dynamic subquery, retry
loop, or autonomous retrieval controller.

The trusted internal G3 `EvidenceBundle` retains `query_id`, retrieval-call
count, query count, deterministic ordering, and provenance. A fail-closed,
bounded conversion produces public `KnowledgeEvidence` and bounded
`DecisionContextItem` seed data. The Engineering run passes those seeds before
the first ToolAgent Decision and disables the duplicate `knowledge_search`
Tool; the legacy `/tool-agent/query` registry and behavior remain unchanged.
Retrieval calls do not increment ToolAgent iteration/tool/error counters, and
the future Unified Runtime still has one logical budget owner.

This stage does not migrate `MinimalEvidenceVerifier`, Grounded Generation,
Finalization Policy, or Citation Validator. It also does not change the
Planner, ToolAgent prompt, Requirement Router, G12 Guard, public API schemas,
or historical artifacts. Those boundaries are prerequisites for the next
reviewed stage and do not authorize ARCH-VERIFY-06 to start automatically.

## ARCH-VERIFY-06 implementation addendum

ARCH-VERIFY-06 implements the next component boundary without introducing a
new verifier algorithm or controller. `EngineeringEvidenceVerifier` delegates
the existing G3 `MinimalEvidenceVerifier`, the existing G12
`evaluate_evidence_requirement`, and the existing `CitationValidator`, then
publishes one immutable `EngineeringVerificationResult`. Only that result's
`can_finalize` and bounded recovery fields are consumed by the existing
ToolAgent finalization point.

Retrieval sufficiency uses the G3 result and explicit coverage truth captured
before RRF merge: direct retrieval has no required IDs, single retrieval has
`q0`, and decomposed plans use the exact ordered `sq1`… IDs. A deduplicated RRF
representative item's query ID cannot erase a covered subquery. G12 remains a
shape-level requirement check. Citation validation checks only whether
referenced `[C#]` IDs exist in the adapted EvidenceBundle context; it does not
claim semantic entailment or claim-level grounding. No citation is
nonblocking; an invalid citation reference is a hard stop.

The recovery boundary is explicit: missing Repository/Git/Test evidence may
use the next existing producer Tool when the current 5/4/2 enforcement allows
it; retrieval insufficiency, incomplete planned coverage, and invalid citation
references are non-recoverable and do not re-enable `knowledge_search` or add a
repair LLM. The legacy endpoint behavior, public API/SSE shapes, prompts,
router, guard contract, counters, and observability outcome isolation remain
unchanged. `ToolAgentRuntime` remains only the execution component and there
is no nested autonomous controller, FinalizationRuntime, or third product
Runtime.

## ARCH-CUTOVER-07 implementation addendum

ARCH-CUTOVER-07 将 Engineering 主链正式固定为：

```text
/engineering/*
  → EngineeringAgentFacade
  → UnifiedEngineeringRuntime
  → ContextResolver
  → EvidencePlanner
  → Requirement Router
  → Adaptive Planned Retrieval / Evidence Aggregation
  → bounded ToolAgent execution component
  → Unified EngineeringEvidenceVerifier
  → single ToolAgent finalization point
  → Engineering response / SSE
```

Production `UnifiedEngineeringRuntime` now requires, at construction time, the
Context Resolver, Evidence Planner, Engineering Retrieval Component,
Engineering Evidence Verifier, and the `LegacyToolAgentExecutionAdapter`.
The compatibility planner, optional core components, direct legacy delegate
branch, and conditional verifier path are not valid assembly modes. Missing a
core component fails fast or leaves the Engineering capability unready; it
never silently downgrades the request to a legacy execution path.

The three Engineering entries—`/engineering/query`,
`/engineering/query/stream`, and `/engineering/query/stream/v2`—share the same
Facade and Unified Runtime. Their difference is observer transport: safe Trace
for the first stream and Rich Activity for v2. `/engineering/knowledge` stays
a status/identity endpoint and does not execute the Agent. `/query`,
`/agent/query`, and `/tool-agent/query` remain independent legacy
regression/historical/debugging paths; they are not redirected to the new
main chain and are not a second product controller.

`LegacyToolAgentExecutionAdapter` remains a thin delegation boundary. It does
not own planning, retrieval, verification, budget, finalization policy, or an
additional loop. `ToolAgentRuntime` keeps the frozen 5/4/2 hard enforcement and
its allowlist/duplicate/error semantics as the bounded Tool Execution Engine
during migration. It is not a second Agent/controller, and there is no
`UnifiedBudget`, `PlannerBudget`, `VerifierBudget`, `RetrievalBudget`, or other
parallel budget ledger.

This cutover is evidenced by deterministic proofs for Knowledge-only,
Repository-only, Cross-source, Change/Test, Contextual follow-up, and failure
semantics. The proofs assert planned retrieval handoff and suppression of the
duplicate `knowledge_search`, dynamic repository/change/test evidence,
standalone context resolution, one accumulated unified evidence sequence, one
verifier/finalization result, bounded recovery, and the existing hard-stop
matrix. Sync, stream v1, and stream v2 preserve the same business result.

The cutover does not change the public question-only schema, Prompt, Router,
Guard semantics, 5/4/2 values, historical Gate facts, or observability outcome
isolation. It is component migration with regression coverage, not a big-bang
ToolAgent rewrite, not a nested autonomous controller, and not a permanent
discarding of G3. `ARCH-EVAL-08` remains the next independent evaluation stage
after this cutover is reviewed.

## Consequences

### Positive

- Architecture Integration Drift 有唯一解释和唯一迁移顺序；
- Context、Plan、Budget、Evidence、Verification、Finalization、Activity 的责任可审计；
- ToolAgentRuntime 的成熟安全执行机制可以渐进复用，不需要临时复制一套 Agent；
- G3 能力得到保留，G11/G12 的 evidence/guard work 可以落到统一 lifecycle；
- 历史 Gate 结果与新架构评估分离，避免“迁移后数字变了就重写历史”。

### Trade-offs

- 迁移期会同时存在 legacy endpoint、ToolAgentRuntime execution component 和 target contracts，需要 adapter 与回归测试；
- 当前已获得 G3/G8 的 Context/Plan、有限 Knowledge Retrieval 与统一
  `EngineeringEvidenceVerifier` 组件接入；Grounded Generation 的语义评估
  与最终 control-plane cutover 仍必须按阶段推进；
- single controller 约束限制了为了局部便利而引入 nested Agent 或独立 backend loop；
- G12 shape-only Guard 与 Citation-ID validation 仍不能替代完整语义
  verifier；本阶段明确保持这一边界，后续只能在架构顺序内单独评估。

## Compatibility and guardrails

- Gate 1～G12 frozen facts 不重写；Gate 2 / Gate 3 sealed/formal 不因迁移重新调参或重跑；
- legacy `/query`、`/agent/query`、`/tool-agent/query` 与三条 Engineering
  entry 在迁移期间保持回归；legacy routes 独立保留，Engineering 三条 entry
  共用一个 Facade/Unified Runtime；
- G12 question-only contract 保持，不向 request 注入 evaluator Gold、case 或 source metadata；
- `P1-OBS-03A-R1-MICRO` 继续是 `ACCEPT / CLOSED`，Activity/Observability 只读投影，不改变 runtime outcome；
- 不新增 Multi-Agent、不做 Persistence/Citation UI；ARCH-RETRIEVAL-05 的
  有限 Knowledge Retrieval、ARCH-VERIFY-06 的统一 Verification seam 与
  ARCH-CUTOVER-07 的严格 assembly 均保持组件边界；ARCH-EVAL-08 仍待独立审计；
- G3 `MinimalEvidenceVerifier`、G12 evaluator 与 `CitationValidator` 只由
  一个 `EngineeringEvidenceVerifier` 编排并产生一个 trusted result；不
  允许三个独立 finalizer、citation repair LLM 或 Knowledge retry；
- ARCH-CUTOVER-07 的 Engineering production assembly 必须提供全部核心
  component 与唯一 execution adapter；缺失时 fail-fast/unready，不得静默
  fallback 到 legacy path；三条 Engineering entry 必须共用同一 Facade/Runtime；
- 后续必须先做 component migration，不能 big-bang rewrite、不能永久丢弃 G3、不能引入第三个产品 Runtime。

## Non-decisions

本 ADR 不决定具体 Prompt、provider/model、retrieval threshold、budget 数值、Guard 算法细节、Persistence schema、Citation UI 或 product rollout。它也不授权重跑 Formal 或改变任何 Gate artifact；这些只能由后续阶段在本架构边界内单独提出并审计。
