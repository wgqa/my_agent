# G12 Baseline A Manual Gold

## 1. 这次 Baseline 评测回答了什么

G12-03 的唯一有效 Baseline A 是：当前 Engineering v2、当前 ToolAgentRuntime、现有 7 个 Tool、`5 / 4 / 2` budget，并且没有 Finalization Guard。Formal run 为 `g12-baseline-a-formal-20260825-195305`，使用冻结的 16-case dataset `gate12-v1-630fc8b527c2`。

Baseline A 不是理想 Agent，也不是带 verifier 的未来系统。它提供一个可复查的现状对照，后续任何 Prompt-only Control 或 System C 结果都必须和这个快照区分开。

## 2. Manual Gold 结果

Reviewer 对每个 case 做了 Full Task Success、Evidence Coverage、Claim Grounding 和 Evidence Correctness 判断。Full Task Success 的冻结分布是：

| Verdict | Cases | Rate |
| --- | ---: | ---: |
| PASS | 2 | 0.125 |
| PARTIAL | 8 | 0.500 |
| FAIL | 6 | 0.375 |

因此严格 Full Task Success 是 `2/16 = 0.125`，但 `PARTIAL-or-better = 10/16 = 0.625`。这不应被描述成“Agent 完全不可用”：多数 case 至少有部分有用内容，但只有两条完整满足核心 obligation。

Evidence Coverage 为 `FULL=1`、`PARTIAL=8`、`NONE=7`。Claim Grounding 为 `PASS=1`、`PARTIAL=8`、`FAIL=7`。这些是 Reviewer 的语义判断，不是 runner 从文件名、Tool 次数或 evidence 数量自动推导出的分数。

## 3. Family 与 repository 分布

四个 task family 的 Full Task Success 分布如下：

| Family | PASS | PARTIAL | FAIL |
| --- | ---: | ---: | ---: |
| Theory <-> Code | 1 | 3 | 0 |
| Change Impact <-> Test | 1 | 2 | 1 |
| Diagnosis / Config | 0 | 1 | 3 |
| Docs <-> Code | 0 | 2 | 2 |

Diagnosis / Config 最弱：四条中三条 FAIL，只有一条 PARTIAL。这与跨文件定位、实现证据获取和诊断结论之间的 grounding debt 一致。

按 repository 看，`my_agent` 为 `PASS=2, PARTIAL=3, FAIL=3`，`pydantic_ai` 为 `PASS=0, PARTIAL=5, FAIL=3`。两侧都出现系统性 evidence debt，因此不能把问题归因于单一 repository 的偶然表面。

## 4. q004 与 q006 是重要对照

`q004` 的 automatic Evidence Sufficiency 为 PASS，但 Manual Full Task Success 只有 PARTIAL。这说明 shape sufficient 只代表 required evidence kind/path shape 满足最低结构，不能自动证明答案的语义正确性或所有 obligation 都被完成。

`q006` 的 automatic Evidence Sufficiency 为 FAIL，但 Manual Full Task Success 为 PASS。这说明一个答案可能被 Reviewer 认为完成了核心任务，却没有达到 Evidence-Grounded Reliability 所要求的完整公开证据形状。

两条 case 一起说明：

```text
shape sufficient != semantic correctness
semantic correctness != evidence-grounded reliability
```

所以 G12 的 Guard、Evidence Coverage 和 Claim Grounding 不能由单一自动布尔值代替。

## 5. project_test evidence 的缺失

本次自动 evidence kind 统计中 `project_test` 为 `0`。这不是说所有回答都不谈测试，而是说 Agent 没有通过 public evidence contract 获得可供自动结构判断的 `project_test` evidence。候选路径、答案中的测试名称和真正读取测试源码之间不能混为一谈。

这也解释了为什么 Change Impact 结果即使包含部分有用的 diff reasoning，仍不能自动声称 test evidence 已经建立。candidate provenance、evidence presence 和 semantic test coverage 是三个不同层次。

## 6. Provider call metric correction

初始 runner 把 case 的 `provider_call_count` 写成所有 `decision_completed` 事件中的最大值，得到 `17`、平均 `1.0625`。这与 Runtime metadata 的语义不符：每个 `decision_completed` 记录的是该次 Decision 的本地 `AgentDecisionCallMetadata.call_count`；普通 Decision 为 `1`，发生一次 repair 的 Decision 为 `2`。

正确的 case 聚合是对所有 `decision_completed` 的本地 count 求和。离线重算得到 provider calls total `54`，平均 `3.375`。例如 `[1,1,1,1]` 得到 `4`，`[1,2,1]` 也得到 `4`。

这是 evaluator aggregation bug，不是 product/runtime 行为变化。原始 Formal artifact 保持不变，correction artifact 只 supersede cost metric；所有其他 automatic metrics、Manual Gold 和 Baseline capability interpretation 不因这个修复重跑或改写。已有 VALID Formal 也不需要重新调用 Provider。

## 7. Capability result 与 evaluator metric bug 的边界

本次结论分成两层：

- Baseline A Formal provenance 有效，运行结果可用于审计。
- Evidence-Grounded Reliability 为 NEGATIVE，整体 Capability 为 MIXED。

`2/16` Full Task Success、`1/16` Full Claim Grounding、`12/16` premature finalization 和 `0` project_test evidence 支持负面 reliability 结论；`10/16` partial-or-better 说明系统仍有局部能力。

Provider call 的 `17 -> 54` 是 evaluator cost metric 更正，不能被夸大成产品能力变化，也不能因为 metric bug 把整个 Formal 判为 invalid。相反，Formal identity、case result SHA、manifest SHA 和 correction rule 被一起记录，保证 Reviewer 能区分原始输出、离线重算和语义 Gold。

## 8. 当前边界

G12-03 已冻结 Baseline A Manual Gold。没有修改 Prompt、Runtime、Tool、API、frozen cases 或 Finalization Guard，也没有运行第二次 Provider Formal。下一步是 G12-04A System C Acceptance Contract；System C 在获得独立授权前不应提前实现。
