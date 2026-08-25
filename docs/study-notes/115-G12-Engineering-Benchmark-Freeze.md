# G12 Engineering Benchmark Freeze

## 1. 为什么要从 24 条候选收敛到 16 条

Candidate pool 是 dataset construction 的工作区：每个 task family 和每个 repository 都保留三条可审计候选，给 Reviewer 足够的拒绝空间。Final benchmark 则是之后 Baseline A 才能使用的稳定评测输入。二者不能混用：候选可以继续解释其构造 provenance，final case 必须有独立、不可漂移的 case identity。

G12-02B 的 Reviewer selection 固定为 16 条：四个 family 各四条、`my_agent` 与 `pydantic_ai` 各八条，并且每个 family/repository 组合正好两条。Final ID 改为 `g12q001` 到 `g12q016`，同时保存其 `source_candidate_id` 与 source candidate SHA-256。因此未来可以从任一 final case 回溯到 24-case construction pool，但不能把 pool 中未选条目当成 Formal case。

## 2. Reviewer 拒绝的含义

拒绝不等于 candidate 的 source proof 一定错误。`g12c009` 的 historical Change provenance 在 02A-R1 已经修复为有效：diff anchor 绑定 `base..head`，test source 绑定 `head_ref`。它仍被拒绝，因为预算控制主题与先前 G11 development topic 重叠，降低了独立性。provenance valid 不等于 dataset independent。

`g12c024` 也说明了另一种边界。CallToolsNode 与 ToolManager 的实现 ownership 分散，表示单一 source window 未必足够；这属于 evidence insufficiency。它本身不推出 document 与 code `PARTIALLY CONSISTENT`，更不能为了凑 Docs label 配额制造 drift。因此该草案未进入 final Gold。

## 3. 真实分布优先于人为平衡

Final Docs subset 的四条 label 都是 `CONSISTENT`。没有自然接受的 `OUTDATED`、`INCOMPLETE` 或 `PARTIALLY CONSISTENT` case，这会降低该 subset 的 Docs-label discrimination；manifest 必须如实记录这一限制。

这不是 dataset 缺陷可以用编造反例修复。G11-05 已单独保存真实 stale-doc transfer evidence。G12 v1 要评测的每一个 label 都必须由真实 document/code 双边证据支持，而不是由配额要求产生。

## 4. 时间快照与外部仓库

Change case 的 `project_change` 只能来自真实 `base_ref..head_ref` diff；`project_test` 只能来自同一个 `head_ref` 存在的测试正文。测试没有和实现一起改动时，只有它已存在于 head 且不在 changed paths 中，才称为 unseen test。Final 16 条里只有 `g12q007` 是这种 unseen case。

两个 project snapshot 同样是 contract 的一部分：

| Project | Frozen commit | Final cases |
|---|---|---:|
| `my_agent` | `465dd65e950e9c4a119820a5a27f558e74ad5892` | 8 |
| `pydantic/pydantic-ai` | `bfa8e9187b86aad7ec583665ab2743fadea458b1` | 8 |

Evaluator metadata 留在 evaluator checkout；Agent 只搜索 isolated project checkout。这样外部 repo transfer 既保留真实工程表面，也不会把 Gold、case identity 或结论暴露给被评测的搜索空间。

## 5. Freeze identity 与可复查性

每个 final case 用 canonical JSON（UTF-8、`ensure_ascii=False`、sorted keys、紧凑 separators）计算 SHA-256。benchmark JSONL、reviewer selection、candidate pool 与 repository manifest 的 SHA 都写入 final manifest。`gate12_dataset_freeze_id` 由 final benchmark SHA 稳定派生，不含时间戳或随机 UUID。

Validator 重新检查：candidate-to-final semantic payload 深度相等、Reviewer mapping、16-case distribution、Docs label limitation、Change temporal proof、isolated clean checkout、knowledge probe，以及本地绝对路径不进入 tracked artifact。这些 checks 只保证评测输入和 provenance 的结构可信；它们不自动判定 Agent answer 的 relevance、claim grounding 或 task success。

## 6. 为什么现在才能运行 Baseline

freeze 前运行 provider 会让输入、Gold 与结论一起漂移，无法区分 Agent 行为变化与 dataset 变化。现在的顺序是：

```text
Candidate pool (24)
    -> Reviewer selection (16)
    -> Canonical final dataset freeze
    -> G12-03 Baseline A evaluation harness
    -> real-provider Formal only after harness review
```

G12-02B 不启动 Baseline A、不实现 Finalization Guard，也不更改 Prompt、Runtime 或 Tools。它只让下一阶段拥有一个独立、可复查、不会被 evaluator metadata 污染的 benchmark 输入。
