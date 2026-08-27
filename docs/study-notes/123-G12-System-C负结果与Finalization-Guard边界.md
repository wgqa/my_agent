# 123. G12 System C 负结果与 Finalization Guard 边界

## 1. 这份记录冻结什么

本笔记记录唯一有效的 System C Formal 及其人工 Gold。它是 evaluator-side
结果记录，不是对产品代码的再次修改，也不是下一轮调参的授权。

System C 的冻结干预只有两项：通用的 deterministic typed Evidence Requirement，
以及 system-level Finalization Guard。其余条件与 Baseline A 相同：16-case
benchmark、两个 project checkout、provider/model、Engineering Prompt v2、1200
output cap、`5 / 4 / 2` budget、7 个 Tool 和 Knowledge corpus 均保持不变。请求体
仍只有 `question`，没有 case ID、task family、Gold obligation、source path 或
requirement metadata。

原先的假设是：如果系统在 `completed` 前阻止 evidence shape 不足的答案，
Evidence Sufficiency、Grounding 和整体任务可靠性会改善，同时不发生严重的
Task Success 或成本回归。这个假设必须与“Guard 的状态机实现是否机械正确”分开
判断。

## 2. Formal 有效性边界

早期两次尝试不能用于能力结论：

- `g12-system-c-formal-20260826-173039`：`INVALID / PROVIDER-PLANE FAILURE`；
- `g12-system-c-formal-r1-20260826-191531`：`INVALID / PROVIDER-PLANE FAILURE`。

它们发生在 provider plane，未形成可用于比较的完整 System C 观测。最终有效
run 是 `g12-system-c-formal-manual-20260826-203236`，16 个 case 均已完成请求，
并通过了冻结数据、product、project 和 artifact provenance 检查。

环境事实应准确表述为：

> Agent-managed execution environment showed reproducible APIConnectionError, while manually launched equivalent API processes succeeded.

这不等同于武断断言某个 sandbox 必然阻断 DeepSeek。最终结果是 `VALID`，所以它的
失败是实验结果而不是 infrastructure invalid。

## 3. A 与 C 的结果

自动指标只判断确定性结构，不判断答案语义：

| 指标 | Baseline A | System C | 变化 |
|---|---:|---:|---:|
| Evidence Sufficiency | 2/16 | 2/16 | 0 |
| Premature Finalization | 12/16 | 9/16 | -3 |
| Required-tool complete | 6 | 7 | +1 |
| Completed | 14 | 11 | -3 |
| Refused | 1 | 4 | +3 |
| Failed | 1 | 1 | 0 |
| Provider calls | 54 | 57 | +3 |
| Tool calls | 37 | 39 | +2 |
| Iterations | 53 | 56 | +3 |

System C 的其他自动结果是：`forbidden_tool_calls=0`、structured parse failure
`1`、duplicate Tool stops `2`、budget stops `0`、平均 latency `7437.66 ms`。
成本预算通过，但 duplicate stop 上限没有通过。

人工 Gold 的结果是：Full Task Success `PASS=2 / PARTIAL=7 / FAIL=7`，严格成功
率 `2/16`，partial-or-better `9/16`；Evidence Coverage 为
`FULL=1 / PARTIAL=8 / NONE=7`；Evidence Correctness 为
`PASS=5 / PARTIAL=4 / FAIL=3 / NO_EVIDENCE=4`；Claim Grounding 为
`PASS=1 / PARTIAL=5 / FAIL=10`。

因此不能说 System C 改善了 full task success 或人工 evidence coverage：前者
保持 `2/16`，后者分布完全不变；partial-or-better 从 `10/16` 降到 `9/16`，
Grounding FAIL 从 `7/16` 增到 `10/16`。也不能把这些结果夸大成整个 Agent
不可用，仍有 2 个完整 PASS 和 9 个 partial-or-better。

## 4. Acceptance Contract 判定

按冻结的 Acceptance Contract，结果为：

```text
run_validity       = VALID
system_c_acceptance = FAIL
final_classification = VALID / FAIL
```

主要未通过项：

- premature finalization `9`，要求 `0`；
- overall Evidence Sufficiency `2`，要求至少 `8`；
- Change family `0`，要求至少 `1`；Diagnosis family `0`，要求至少 `1`；
  Docs family `0`，要求至少 `1`；
- Change `project_test` 为 `0`，要求至少 `2`；
- Diagnosis cross-file shape 为 `0/3`，要求至少 `2/3`；
- Docs bilateral evidence 为 `0`，要求至少 `2`；
- Claim Grounding PASS 为 `1`，要求至少 `3`；FAIL 为 `10`，要求最多 `5`；
- duplicate Tool stops 为 `2`，要求最多 `1`。

通过项也必须保留：Full Task Success PASS=`2` 达到最低线，partial-or-better=`9`
达到最低线，refused=`4`、failed=`1` 在限制内，provider/tool/iteration cost
预算通过，forbidden Tool calls 为 `0`。这是一份 mixed metric profile 下的有效
FAIL，而不是只挑失败数字的叙事。

## 5. q004 与 q006：两个必要对照

`q004` 的 automatic Evidence Sufficiency 是 PASS，但人工 Full Task Success
只有 PARTIAL。结构上 `knowledge + project_doc` 满足最低 shape；Gold 语义上还
需要 StateGraph knowledge 与 CallToolsNode implementation evidence。实际主要读
到 `docs/agent.md`，没有关键的 `pydantic_ai_slim/pydantic_ai/_agent_graph.py`。
所以：

```text
Structural evidence sufficiency does not imply semantic evidence sufficiency.
```

`q006` 的人工 Full Task Success 是 PASS，但 automatic Evidence Sufficiency 是
FAIL，且 `premature_finalization=true`。它取得了 `project_change`，没有取得
`project_test`，但答案仍正确覆盖了大部分 resolver failure semantics。因此：

```text
Semantic correctness does not imply evidence-grounded reliability.
```

这两个 case 防止把 automatic shape 当成答案正确性，也防止把 evidence guard
误解成“只要拒绝就算成功”。

## 6. Root cause 分层

第一层是 requirement recall。冻结 Router 是 bounded lexical semantics；真实
自然语言经常不包含精确的 `test`、`regression` 等 trigger。于是某些 Gold 需要
evidence constraint 的问题得到 `NO_ADDITIONAL_REQUIREMENT`，Guard 根本不会被
触发。`q006` 没有明确的 test/regression 词，因此没有触发冻结的
`CHANGE_TEST_V1`。这是本次结果后的 diagnosis，不是修改 Router 的理由。

第二层是 evidence planning。`q005` 和 `q007` 没有稳定执行
`find_tests -> read_project_context(test)`，而是继续花费预算在 `git_diff` 或
`code_search`，最后安全拒答。Guard 可以阻止 unsupported completion，却不能
自己产生缺失的 `project_test`。

第三层是 semantic relevance。`q010` 确实发生过一次 Guard block，之后取得了
`project_code`，但路径是 `core/adaptive_retrieval/policy.py`；Gold 需要的是
`core/query_planning/openai_compatible.py` 与 `core/query_planning/planner.py`。
因此 evidence kind 存在不等于实现区域相关，更不等于 claim 已被支持。

这三层分别对应 router recall、evidence planning 和 semantic relevance。不能用
给 frozen benchmark 补关键词、写 case 特判或加入第二个 LLM 来把它们混成一个
Guard 修复问题；本次结果之后不修改 Router，也不对同一 benchmark 重跑。

## 7. 实现正确性与实验效果

Formal 中真实观察到 Guard block，说明 deterministic Finalization Guard 的
intervention path 可达；这支持实现级的机械有效性。它不支持干预效果假设，因为
9 个 completed case 仍然 evidence-insufficient，且整体 Sufficiency 没有上升，
人工 coverage 没有改善。

准确的结论是：

> The deterministic Finalization Guard implementation is mechanically valid and its intervention path was observed in the Formal run. However, the frozen hypothesis that this minimal Guard alone would materially improve evidence-grounded reliability was not supported by the transfer benchmark.

中文可概括为：Finalization Guard 的 Runtime 状态机与确定性实现本身成立，正式
实验中也真实观察到 block 行为；但“只增加最小确定性 Finalization Guard 即可
显著改善 evidence-grounded reliability”的实验假设未得到支持。

不要写成“Guard implementation failed”，也不要写成“Guard succeeded”。前者
混淆实现有效性与实验效果，后者忽略了 frozen acceptance gate 的失败。

## 8. 负结果与下一步边界

Negative result 的含义是：在冻结条件、冻结 benchmark 和一次有效 Formal 下，
该最小干预没有达到预注册的 evidence/grounding/guard acceptance gates。它不是
整个 Evidence-Grounded AI Engineering Agent 项目的总失败，也不是可以事后修改
规则再证明成功的邀请。

这个 run 已是有效 FAIL，执行 `No rerun`。不能挑选更好的单 case，也不能为了
结果选择重跑 16 cases。后续 G12 final close 只能把本 assessment、Manual Gold
和 provenance 作为输入；本次任务不实现新的 Router、Guard、verifier 或 Prompt
tuning。

## 9. 面试解释

可以用四句话回答：

1. 我先冻结了 Baseline A、System C 干预和 acceptance thresholds，避免看结果后
   改尺子。
2. 最终本机启动的两个 API 产生了一个 provenance 有效的 16-case Formal；早期
   provider-plane failure runs 则单独保留为 invalid，未混入结论。
3. Guard 的 block 路径真实执行，但 requirement recall、测试证据规划和语义
   relevance 仍然失败，所以 Sufficiency 仍为 `2/16`，并有 `9/16` premature。
4. 因此实现是 mechanically valid，实验假设是 `VALID / FAIL`；下一步是如实收口，
   不是围绕 benchmark 刷关键词或重跑挑结果。

本笔记与 `evaluation/gate12/system_c_final_assessment_v1.json`、
`system_c_manual_review_v1.jsonl` 和 `system_c_manual_review_summary_v1.json`
共同构成 G12 final close 的输入。
