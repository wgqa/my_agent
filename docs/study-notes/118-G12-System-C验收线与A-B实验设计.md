# G12 System C 验收线与 A/B 实验设计

## 1. 为什么先冻结验收线

System C 会引入 typed Evidence Requirement 和 system-level Finalization Guard。它可能改变完成率、拒答率、证据获取、成本和可靠性。如果看到结果后才决定阈值，就无法判断系统是否真的改善，只能得到一次事后解释。

所以顺序必须是：

```text
Baseline A 冻结
    -> 验收阈值冻结
    -> 审计 intervention identity
    -> 才能运行 System C
```

G12-04A 只冻结 evaluator/design contract，不实现 Guard，也不运行 Provider。

## 2. Primary gate 与 Guard invariant

最严格的 Guard invariant 是 `completed AND evidence_sufficient=false` 必须为零。它不是普通平均分，而是一个 correctness gate：只要还有一个证据不足却完成的 case，Guard 的核心行为就没有完全成立。

Primary utility 与 evidence threshold 则是整体目标：Evidence Sufficiency 至少 `8/16`，Full Task Success 不低于 Baseline 的 `2/16`，PARTIAL-or-better 至少 `9/16`。这三者分别回答：结构证据是否增加、完整任务能力是否退化、部分有用答案是否被拒答策略吞掉。

## 3. 为什么不能 always-refuse

如果 Agent 永远拒绝，它几乎可以避免 premature finalization，但没有完成工程任务。拒答上限和 partial-or-better 下限因此同时存在：Guard 应该阻止不安全完成，而不是把所有工作转化成拒绝。

System C 还单独限制 `INSUFFICIENT_EVIDENCE_TO_FINALIZE` 的次数。有限拒答可能是正确的安全动作，拒绝全部任务则是 utility collapse。

## 4. q004 与 q006 的对照

q004 的 Baseline shape 足够，但 Manual Task Success 只有 PARTIAL，说明：

```text
shape sufficient != semantic correctness
```

q006 的 Baseline shape 不足，但 Manual Task Success 是 PASS，说明：

```text
semantic correctness != evidence-grounded reliability
```

这两条对照防止我们犯两个错误：把证据计数当成语义裁判，或把 Guard 设计成“不满足 shape 就无脑拒绝”。System C review 必须专门检查这两个 trade-off。

## 5. Utility、Grounding 与成本

System C 不是只看 Evidence Sufficiency。Claim Grounding PASS 至少 `3/16`、FAIL 不超过 `5/16`，用于观察答案中的具体 claim 是否更有根据。Full Task Success 不能低于 `2/16`，PARTIAL-or-better 至少 `9/16`，用于防止安全机制带来严重 utility collapse。

成本也分成两类：provider calls、Tool calls、iterations 是较确定的工程成本，分别限制为 `72 / 52 / 72`；网络 latency 受环境影响较大，因此必须报告，但平均 latency 超过 Baseline 两倍只标记 `MAJOR COST REGRESSION`，不自动把 Formal 判成 INVALID。

Baseline provider metric 已经离线更正为 `54`。修正原因是每个 `decision_completed` 的 `provider_call_count` 是该次 Decision 的 local metadata，case-level 应跨 Decision 求和。这个 evaluator metric bug 不需要重跑原始 Provider Formal，也不改变产品行为。

## 6. PASS、MIXED、FAIL、INVALID

这四个词不是同义的“好/坏”：

- `INVALID`：基础设施、provenance、dataset、project binding、Prompt/control drift 或 Gold leakage 破坏了实验有效性，不能得出能力结论。
- `FAIL`：Formal 有效，但 Guard invariant 或关键质量/utility/reliability threshold 失败。
- `MIXED`：Guard correctness 通过，Evidence Sufficiency 至少 `6/16`，没有重大 collapse，但完整 PASS gate 尚未全部满足。
- `PASS`：完整 integrity、primary、utility、grounding、cost 和 reliability gates 都通过。

有效 FAIL 不应通过反复运行挑出最好结果。INVALID 只有在基础设施修复后才允许完整重跑，而且旧 invalid artifact 必须保留。

## 7. System C 与 A/B 的可比性

System C 必须保持同一 benchmark、provider/model、Engineering Prompt v2、1200 cap、`5 / 4 / 2` budget、7 Tools、项目 commits 和 Knowledge corpus。唯一 tested factor 是 typed Evidence Requirement + system-level Guard。

Requirement 由 generic product/system logic 产生。Evaluator 不能把 case ID、task family、Gold obligations 或 source paths 发给模型，也不能在 router 中硬编码某个仓库或题目。实现测试应优先使用 synthetic non-benchmark queries，避免把 final dataset 当成训练集。

## 8. 为什么 System C 失败仍有价值

实验并不预设 System C 一定 PASS。它可能证明：Guard 能消除 premature，但拒答过多；证据 shape 增加，但 grounding 没有改善；或者成本超出预算。只要 Formal provenance 有效，这些都是下一轮设计的证据。

真正需要避免的是把失败解释成“再跑一次直到通过”，或把 INVALID 与 FAIL 混为一谈。冻结 acceptance contract 的意义，就是让 System C 的结果无论 PASS、MIXED、FAIL 还是 INVALID，都能被准确解释。
