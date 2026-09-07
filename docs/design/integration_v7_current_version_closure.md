# Integration v7 Current Version Closure

> ARCH-INTEGRATION-17：给当前最终 Product 一个可信、有限、可解释的
> Integration v7 结论，正式结束 Architecture Integration / Evaluation 施工期。
> 本文档是阶段结论文档，不是新的 Study Note，也不开启任何新的评测或调参。

**分类冻结：** ARCH-INTEGRATION-17 = **CONDITIONAL ACCEPT / CLOSED**（2026-09-07）

## 1. 结论的三层拆分

CONDITIONAL ACCEPT 不是把 architecture、product quality、benchmark quality
压成一个模糊的 PASS/FAIL，而是显式区分三层：

| 层 | 结论 | 含义 |
| --- | --- | --- |
| Architecture Integration | **ACCEPT / CLOSED** | v7 统一架构集成已经完成，可以进入 Productization / Demo / 校招掌握阶段 |
| Current Product Semantic Quality | **CONDITIONAL / KNOWN LIMITATIONS** | 当前 Product 在 bounded AI Engineering Agent 场景下有真实有效能力，但 semantic grounding、evidence acquisition、over-refusal 仍有明确已知限制 |
| Benchmark / Generalization | **NOT CLAIMED** | 不宣称 Dev benchmark solved，不宣称泛化性能；Holdout 保持 sealed |

因此它不是：整个项目 FAIL；也不是：18 Dev 全 PASS、benchmark solved、
production-grade、semantic quality fully proven。

## 2. Current Product identity 与等价性证据

- 当前 repository HEAD：`25ff4bc8573221fc55b949c5e804938b0013ff66`
- 15D semantic review 审查的 Product candidate：`6d7e58f1e8c1f2bdaab091c453855b6eee53036b`
- 机械等价性检查（2026-09-07 执行）：
  `git diff --exit-code 6d7e58f 25ff4bc -- core api ui` → **ZERO DIFF**。

也就是说：15D 所审查的 Product 行为可以作为当前 Product 主链行为的直接
证据。从 `6d7e58f` 到当前 HEAD，Git 变化只发生在 evaluation / docs / tests
（评测协议、语义审查、负实验与回滚），没有 Production tree 变化；期间唯一的
Production 干预（16A recovery repair）已被 16C 逐字节回滚。

## 3. 事实源层级

本 Closure 只基于以下事实源，不引入任何新的评测框架：

1. 当前 Git `25ff4bc`；
2. `docs/roadmap.md` v7 Architecture Constitution；
3. `evaluation/integration_v7/reviews/dev_semantic_15d_6d7e58f_v1/`（15D 语义审查 artifact）；
4. `docs/study-notes/134-Missing Evidence Recovery Decision Repair.md`（16A→16B→16C 负实验闭环）；
5. 已 ACCEPT 的 committed architecture / evaluation tests。

`docs/status.md` 只是待更新状态表；其早期 `NEXT = ARCH-EVAL-08B` 状态已被
后续真实 Git 历史取代，本次一并纠正，不得以旧状态覆盖后文事实。

## 4. Current Architecture（冻结不变）

正式身份：**Evidence-Grounded AI Engineering Agent**。

架构继续冻结：

- **Single Engineering Agent**
- **one trusted control state**
- **one logical Budget Owner**（ToolAgentBudget 5/4/2）

主链（v7 冻结形态）：

```text
EngineeringAgentFacade
    ↓
UnifiedEngineeringRuntime
    ↓
Context Resolver
    ↓
Evidence Planner
    ↓
Requirement Router
    ↓
Planned Knowledge Retrieval / Aggregation
    ↓
Bounded ToolAgent execution component
    ↓
Knowledge / Code / Git / Test Evidence
    ↓
EngineeringEvidenceVerifier
    ↓
single finalization point
```

`ToolAgentRuntime` 是统一 Runtime 的 **execution component**，不是第二个
Agent/controller。本文档不重画任何 Multi-Agent 架构；Evidence Backends
（Knowledge / Code / Git / Test）继续为单一 Agent 提供证据，不各自成为
独立 Agent。

## 5. Capability Evidence Matrix

### A. VALIDATED / SUPPORTED（有真实证据支持）

- Unified single-control-plane assembly（Facade → UnifiedEngineeringRuntime 主链装配，组件缺失 fail-fast/unready）；
- 5/4/2 bounded ToolAgent budget（frozen，未因任何后续阶段放宽）；
- Knowledge / Repo / Git / Test 异构 Evidence Backends 接入同一 bounded Runtime；
- Context / Planner / Retrieval / Requirement / Verifier / Finalization 主链 integration（ARCH-CUTOVER-07 起经 09～13 系列保持）；
- kind-aware project evidence acquisition contract（missing_evidence_groups、distinct code path floor、evidence kind 分类）；
- structured Action parsing + bounded parse repair（v1 既有机制，16C 后仍保留）；
- Runtime finalization enforcement（finalization verifier、recovery feasibility、fingerprint no-progress、hard budget、INSUFFICIENT_EVIDENCE_TO_FINALIZE）；
- safe trace / bounded semantic evaluation artifacts（无 raw CoT/provider output/prompt/API key 落盘）；
- Dev semantic review + failure attribution loop（15C contract + 15D 逐 case 语义审查）；
- evidence-based negative experiment rollback discipline（16A→16B→16C 完整链路）。

**特别记录（premature finalization 边界澄清）：** 15B 真实 Dev 中**没有观察到**
`completed && runtime_requirement_state.satisfied=false` 的 Runtime premature
finalization。历史上 mixed 口径的 `premature_finalization` 指标不得再被解释成
Guard failure——Guard 的硬执行边界在全部 VALID 运行中保持成立；已知的语义
质量问题属于 answer 质量（见 C 类），不属于 Guard 放行失败。

### B. PARTIALLY VALIDATED（有证据，但不应写成全面 PASS）

按 15D 语义审查的 task family 证据水平：

- Repository understanding（repo_only）
- Theory ↔ Code mapping（theory_code）
- Docs ↔ Code（docs_code）
- Change / Test（change_test）
- Diagnosis（diagnosis）
- Context follow-up（context resolution）

对应 15D 总量：**18 total / 16 VALID / 2 INVALID**（v7d002、v7d010 为
worker_process_failure）；Terminal：**13 PASS / 3 FAIL / 2 INVALID N/A**。
这些 family 都有真实运行与语义审查证据，但每个 family 都带有 C 类限制，
不因 Closure 而升级为 PASS。

### C. Known Limitations（原样面对，不为 Closure 重新打开 Dev tuning）

15D committed failure distribution（18 reviews，多标签）：

```text
evidence_acquisition          12
semantic_grounding             8
unsupported_material_claim     8
answer_obligation_missing      6
terminal_outcome               3
refusal                        3
infrastructure                 2
context_resolution             1
```

Grounding 分布：SUPPORTED 3 / PARTIAL 7 / UNSUPPORTED 1 /
NOT_APPLICABLE_NO_CLAIM 5 / NOT_APPLICABLE_INVALID 2。
Refusal 分布：OVER_REFUSAL 3 / JUSTIFIED 2。

这些是当前已知限制的正式记录。Closure 不因此重新打开 Dev tuning（见 §10）。

## 6. 反直觉结论（审计必读）

**6.1 Runtime satisfied ≠ semantic complete。**
15D 中存在 runtime requirement satisfied 但 obligation 不完整的 cases：
`v7d001、v7d003、v7d005、v7d007、v7d008、v7d014`。Runtime 的结构性
evidence 契约满足不代表答案义务被完整覆盖。

**6.2 Gold obligation full ≠ grounded。**
所有 obligation FULL 但 grounding ≠ SUPPORTED 的 cases：
`v7d006、v7d013、v7d015、v7d016`。答案可能覆盖全部义务，但本轮并未取得
支持关键 claim 的 public evidence（gold source proofs 不属于本轮证据）。

**6.3 Router-Gold mismatch ≠ Router bug。**
`router_gold_contract_match=false` 但语义审查无失败的 cases：
`v7d011、v7d017、v7d018`；同时 `router_gold_contract_match=true` 但存在
semantic failure 的 cases：`v7d003、v7d009、v7d012`。Router 与 Gold 契约的
字面匹配与最终语义质量是两个维度，因此本 Closure 不得表述为
"Router accuracy 很低"或"Router 必须继续调"。

## 7. Negative Experiment 正式记录：16A / 16B / 16C

- **ARCH-PROD-16A = VALID EXPERIMENT / NOT PROMOTED**
  （Missing-Evidence Recovery Decision Repair：blocked-but-feasible 时对
  premature terminal action 做至多一次 bounded repair，要求模型改选 ToolCall；
  不改 main prompt identity，不放宽 5/4/2，不改写模型参数）
- **ARCH-INTEGRATION-16B = REAL DEV COMPLETE / NEGATIVE-NEUTRAL RESULT**
  （真实 Dev 18 observed / 16 valid / 2 invalid；recovery repair
  **8 attempts / 8 successes**，0 失败，cases：v7d009、v7d012、v7d017、v7d018；
  机制完全按设计触发并成功）
- **ARCH-PROD-16C = ACCEPT / CLOSED**（evidence-based rollback：四个
  Production 文件逐字节恢复 16A 前 baseline `f29af6ed`，parse repair 与
  Guard 保留）

16B 对照 15B 的描述性结果：

| 指标 | 15B | 16B |
| --- | --- | --- |
| task_completion | 0.8125 | 0.8125 |
| required_evidence_coverage | 0.6875 | 0.6875 |
| tool_coverage | 0.6042 | 0.75 |
| mean llm_calls_total | 3.5 | 4.75 |
| mean latency_e2e_ms | 6857 | 9358 |

并出现 v7d017 refusal-boundary regression signal（frozen 预期拒答 case 在
两次成功 repair 后被推动为 completed；属 descriptive + audit-level signal，
16B 语义评分未执行，不冒充 formal semantic FAIL；v7d018 则为 3/3 repair 后
仍安全拒答的纯粹成本放大）。

最终结论：**更多 Tool activity 没有证明更多有效 Evidence 或更好任务质量**，
因此不继续 recovery-v2。该链路已由 Study Note 134 完整冻结，作为
design judgment / experiment discipline 的正式案例保留。

## 8. Holdout 决策：NOT RUN / REMAINS SEALED

本 Closure 不运行 9 Holdout、不解封、不评分、不补结果。原因：本 Closure
不是在宣称 benchmark superiority、正式泛化性能或进行模型选择，而是在关闭
Architecture Integration。Dev 数据已足以暴露当前 semantic limitations；继续
打开 Holdout 不会改变"不再 benchmark chasing、进入 Productization"的工程
决策。未来只有出现 **major new Product candidate + 明确需要 formal
generalization claim** 时，才另行决定是否授权 Holdout。

## 9. NOT PROVEN（不得进入简历成为硬结论）

- claim-level grounding reliability
- broad semantic answer accuracy
- large-repository scaling advantage
- lower cost than generic LLM
- better accuracy than ChatGPT / generic coding assistant
- production SLA
- real multi-turn conversation product path
- persistent session lifecycle
- formal Holdout generalization

## 10. Current Product Claim Boundary

**可以说：**

当前系统已经证明可以把长期 Knowledge、Repository Code、Git Change 和 Test
等异构 Evidence 接入一个 bounded Engineering Agent Runtime，并对 Tool Use、
Evidence Requirement、Finalization 和 Failure Attribution 做可观察控制；

- architecture integration validated
- evaluation loop validated
- bounded evidence-grounded behavior demonstrated

**不能说：**

- answers are always grounded
- solves repository questions reliably
- outperforms general LLMs

## 11. Dev-driven Production intervention：STOP

自本 Closure 起，Dev-driven Production intervention 停止：不得再因 15D 中
某个 v7d case 打开 Router / Prompt / Guard / Recovery tuning。后续只有出现
真实用户场景 blocker、核心 regression 或 safety issue 时，才在 Productization
阶段另行立项。

## 12. Interview / Project Value

这个项目现在最值得讲的不是"我做了很多 Agent 功能"，而是：从 RAG 出发，
逐步做 Retrieval Evaluation、Structured Tool Use、Repository Evidence、
Context、Unified Runtime、Evidence Verification，最后构建了一套能够真实跑
实验、发现失败、归因失败、甚至否决自己新设计并 rollback 的
Evidence-Grounded AI Engineering Agent。

16A → 16B → 16C 是 design judgment / experiment discipline 的具体案例：
一个机制在 synthetic 测试里完全按设计工作（8/8 修复成功），真实 Dev 却显示
质量指标零变化而成本上升，并出现 refusal-boundary 信号——于是按证据回滚，
保留全部实验历史。这种"用数据否决自己"的纪律，比任何单一功能列表更能说明
工程能力。

## 13. 范围与验证

本 Closure 只涉及三个文件：
`docs/design/integration_v7_current_version_closure.md`（新增）、
`docs/status.md`、`docs/roadmap.md`。无代码、无测试、无评测 artifact 变化，
无 Study Note 135，不重跑任何 benchmark。

执行时的机械验证（2026-09-07）：

- Product equivalence：`git diff --exit-code 6d7e58f 25ff4bc -- core api ui` → PASS（zero diff）；
- 16C rollback contract：`pytest -q tests/test_arch_prod_16c_recovery_rollback.py` → 10 passed；
- 15C semantic review contract：`pytest -q tests/test_arch_eval_15c_semantic_review_contract.py` → 12 passed；
- `git diff --check` → PASS。

**NEXT = PRODUCTIZATION-18A（NOT STARTED）**：Integration v7 架构施工期结束；
下一阶段转向稳定用户场景、演示入口、source/citation presentation、真实
conversation product path 与校招掌握，不继续围绕 Dev cases 调参。18A 本身
未开始，须另行授权。
