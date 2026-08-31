# Unified Engineering Runtime Contract

> ARCH-RUNTIME-02 / CURRENT Study Note 125<br>
> 基线：`dd3afb3e978e2022a0f52370b4847374d8a678ad`<br>
> 目标：先落成唯一 Runtime 控制边界，再在后续阶段迁移 G8/G3 能力。

## 1. 这次任务解决什么问题

项目之前已经有一个“Unified Engineering Agent”的产品入口，但实际 Engineering 主链是：

```text
EngineeringAgentFacade → ToolAgentRuntime → Decision → Tool → Observation → Final
```

这个结构能工作，也保留了 G4 的安全边界，但名字和控制边界还存在 Architecture Integration Drift：Facade 看起来像 Runtime，G3 `AgentRuntime` 和 G8 Context 又在仓库里分别存在。ARCH-RUNTIME-02 的目标不是迁移所有能力，而是先让代码事实和架构事实一致：

```text
EngineeringAgentFacade
        ↓ API/product adapter
UnifiedEngineeringRuntime
        ↓ route requirement once
LegacyToolAgentExecutionAdapter
        ↓ pure delegation
ToolAgentRuntime
        ↓ existing bounded loop + frozen 5/4/2
```

## 2. 为什么 Facade 不是 Runtime

Facade 的职责是给 API、stream 和产品层一个稳定入口。它可以接收 `question` 和 observer sink，转发调用并返回结果，但不应该拥有：

- requirement routing；
- tool loop；
- budget；
- finalization；
- provider retry 或 evidence state。

如果 Facade 自己 route、计数或决定是否完成，它就不再是 adapter，而会成为一个隐藏 controller。当前实现把 `route_engineering_evidence_requirement(...)` 放在 `UnifiedEngineeringRuntime.run(...)`，因此 routing 发生在产品 Runtime 内，并且只发生一次。

## 3. 为什么 ToolAgentRuntime 现在是 execution component

`ToolAgentRuntime` 仍然负责真实执行：它继续执行原有 Decision → Tool → Observation loop，继续执行 allowlist、duplicate-call guard、tool error limit 和 frozen `5/4/2` hard enforcement。这些行为在 ARCH-RUNTIME-02 中不能改变。

但从产品架构看，它不再是 Engineering 产品的顶层身份。顶层身份是 `UnifiedEngineeringRuntime`；ToolAgentRuntime 被放在 `LegacyToolAgentExecutionAdapter` 后面，表示“执行现有 bounded contract”。这使后续可以把 G3 Planner、G8 Context 和其他能力逐个接到统一 seam，而不需要再创建另一个 Agent。

这里的“降级”是 ownership 的降级，不是能力或安全性的降级：

- ToolAgentRuntime 仍是迁移期唯一实际的 Decision → Tool → Observation loop；
- 它仍是 `5/4/2` 的机械 enforcement 位置；
- 它不再拥有 Unified Runtime 之外的产品 controller 身份。

## 4. wrapper 和 nested controller 的区别

### Pure wrapper / execution adapter

一个 wrapper 只做边界适配：

```text
Unified Runtime
  → 已计算的 requirement
  → LegacyToolAgentExecutionAdapter
  → 一次 ToolAgentRuntime.run(...)
```

它不增加 iteration，不增加 provider decision，不重新计 budget，也不改变结果。当前 adapter 只校验底层类型和 requirement，然后把参数交给现有 Runtime。

### Nested autonomous controller

下面这种结构是禁止的：

```text
AgentRuntime loop / budget / finalization
        ↓
ToolAgentRuntime loop / budget / finalization
```

两个 loop 会竞争继续/停止，两个 budget 会产生 double spend 或绕过 hard cap，两个 finalization 会产生互相矛盾的 completed/refused/failed。Trace 也无法说明哪个 controller 对最终结果负责。因此不允许 `AgentRuntime` 套 `ToolAgentRuntime`，也不允许复制 Gate 3 Runtime 形成第二个产品 Runtime。

## 5. 为什么只有一个 logical Budget Owner

目标架构中 `Execution Policy` 是唯一 logical Budget Owner。它定义一次 run 的 budget ledger、allowlist、iteration/tool/error limits 和 stop conditions；Tool Execution Engine 只执行这些限制。

ARCH-RUNTIME-02 还没有把 `5/4/2` 从旧 Runtime 的代码中迁走，因为本任务要求 behavior-preserving。此时的准确说法是：

> `ToolAgentRuntime` 暂时执行唯一的 `5/4/2` hard enforcement，但作为 Unified Runtime 的 execution component，而不是第二个 Agent/controller 或第二个 logical Budget Owner。

因此以下位置都不能再拥有预算：Facade、Planner、Provider、Verifier、Evidence Backend 或另一个 Runtime wrapper。

## 6. 为什么现在不直接迁移 G3 Planner

G3 能力不被永久丢弃，但 ARCH-RUNTIME-02 只建立 Runtime contract。现在直接接入 QueryPlan、Query Decomposition、Adaptive Router、Multi-query Retrieval 或 `MinimalEvidenceVerifier`，会同时改变控制流和行为，无法证明当前任务只是“统一 Runtime 身份”迁移。

G3 的 sealed/formal 事实已经冻结；它们不能因本次接线重新调参或重跑。先完成 Runtime seam 后，G3 才能作为 component 在 `ARCH-PLAN-04` / `ARCH-RETRIEVAL-05` / `ARCH-VERIFY-06` 按 owner 接入。这样保留 G3 的价值，也保持历史实验只读。

G8 同理：本次只预留 `conversation_context` 参数。`None` 正常运行，非 `None` 当前明确抛出 unsupported error，禁止静默丢弃 history。真正消费 Context 要等 `ARCH-CONTEXT-03`。

## 7. 为什么 ARCH-RUNTIME-02 必须 behavior-preserving

这个阶段验证的是架构边界，不是能力提升。若 wrapper 同时改 Prompt、Router、retrieval、Guard、budget 或 finalization，就无法区分结果变化来自“换了顶层 Runtime”还是来自其他因素。

因此本阶段保持：

- `ToolAgentRunResult` 返回类型；
- `/engineering/query` response/schema/status；
- Engineering stream v1/v2；
- `/tool-agent/query` legacy endpoint；
- G12 finalization behavior；
- Rich Activity 与 runtime outcome isolation；
- G4 frozen allowlist 和 `5/4/2`。

## 8. 当前调用链与边界

### Engineering product path

```text
POST /engineering/query
POST /engineering/query/stream
POST /engineering/query/stream/v2
        ↓
EngineeringAgentFacade
        ↓ forwards question + optional sinks
UnifiedEngineeringRuntime.run(user_input, ...)
        ↓ route_engineering_evidence_requirement once
LegacyToolAgentExecutionAdapter.run(...)
        ↓ one delegation
Engineering ToolAgentRuntime.run(
    user_input,
    evidence_requirement=requirement,
    trace_sink=...,
    activity_sink=...,
)
        ↓
ToolAgentRunResult
```

### Historical paths that remain separate

```text
/agent/query       → Gate 3 legacy AgentRuntime       (unchanged)
/tool-agent/query  → Gate 4 legacy ToolAgentRuntime   (unchanged)
/engineering/*     → UnifiedEngineeringRuntime        (new top-level identity)
```

“Separate” here 表示 legacy endpoint compatibility，不表示新建 Multi-Agent。Engineering path 的底层 ToolAgentRuntime 仍是唯一实际 Decision → Tool → Observation loop。

## 9. ARCH-CONTEXT-03 会在哪个 seam 接入

接入点是 `UnifiedEngineeringRuntime.run(..., conversation_context=None, ...)`，而不是 Facade、ToolAgentRuntime 或 Evidence Backend：

```text
user_input
   + conversation_context
          ↓
Context Resolver
          ↓ bounded context snapshot
Evidence Planner / existing runtime components
```

在 ARCH-RUNTIME-02，只有 `None` 被接受；非 `None` 明确 fail-fast。这样下一阶段可以把 Context Resolver 放到统一 Runtime 的第一段，同时保持产品 Facade 仍是薄 adapter，并且不让 history 被静默忽略。

## 10. 常见错误设计

### AgentRuntime 套 ToolAgentRuntime

结果是两个 autonomous controller、两个 budget ledger 和两个 finalization。修复方式是把旧 Runtime 放到 execution adapter 后面，只有 Unified Runtime 拥有产品控制边界。

### wrapper 再计一次 budget

wrapper 不能在调用前后增加 iteration/tool/provider 计数。预算必须只在唯一 execution policy/执行组件链上计一次。

### Facade 和 Runtime 都 route

这会让 requirement 发生两次计算，未来还可能产生两个不一致的 plan。Facade 只转发，Unified Runtime route 一次。

### 静默忽略 `conversation_context`

调用方会误以为历史已被使用，导致错误的 grounded answer。当前非 `None` 必须明确报 unsupported contract，等 ARCH-CONTEXT-03 定义消费语义。

### 顺手改 Prompt / retrieval

这会破坏 behavior-preserving 目标，也可能污染 Gate 2/3/G11/G12 的 frozen 解释。Runtime contract、Prompt、retrieval strategy 和 Guard 语义必须分阶段变更。

## 11. 2 分钟面试表达

> 我先把 Engineering 产品的 Runtime 身份和执行实现分开。以前 Engineering Facade 直接持有 ToolAgentRuntime，虽然有 bounded Decision→Tool→Observation loop，但 Facade、G3 AgentRuntime 和 G8 Context 的架构边界不够清晰。ARCH-RUNTIME-02 新增 UnifiedEngineeringRuntime，由它完成一次 requirement routing，再通过一个纯 delegation adapter 调用旧 ToolAgentRuntime。旧 Runtime 继续负责唯一的 5/4/2 hard enforcement 和工具执行，所以结果、API、stream 和 G12 Guard 行为保持不变。关键约束是一个 Engineering Agent、一个 trusted control state、一个 logical budget owner，禁止 nested autonomous controller。后续 Context 在 Unified Runtime 的 `conversation_context` seam 接入，G3 Planner 再作为 component 迁移，而不是复制或重写 Gate 3 Runtime。

## 12. 本阶段验证什么

Contract tests 验证：

- delegation parity：状态、答案、失败码、计数、trace 和 evidence 保持一致；
- requirement routing 只发生一次；
- provider decision、iteration、tool call、tool error 不增加；
- trace/activity sink 只是 passthrough，activity sink 失败不改变业务结果；
- `conversation_context=None` 正常，非 `None` 明确 fail-fast；
- Facade 不再接受直接 `ToolAgentRuntime`，避免形成双构造方式。

完整回归还需要覆盖 API、两个 Engineering stream、ToolAgentRuntime 和 G12 finalization guard，证明这个阶段建立的是控制边界，而不是隐式改变现有能力。
