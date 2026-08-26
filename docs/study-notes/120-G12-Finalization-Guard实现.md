# 120. G12 Finalization Guard 实现

这篇笔记解释 G12-04C 已实现的第一版 System C 控制面。它记录产品实现和
deterministic tests，不代表 System C Formal 已经运行，也不代表 16 个 frozen
case 已经通过 Router。

## 1. Router 真正匹配什么

`route_engineering_evidence_requirement(question)` 只接收用户问题，先做
Unicode NFKC、casefold、空白归一化和有界标点归一化，然后匹配有限的通用
signal family。它不读仓库、Tool observation、benchmark 或 Gold，也不调用
LLM、embedding、Knowledge 或外部 NLP。

匹配规则和优先级是冻结的：

```text
CHANGE_TEST
  change / commit / diff / 变更
  AND test / regression / 测试 / 回归

DOCS_CODE
  documentation / README / doc / 文档
  AND implementation / code / 实现
  AND consistency / correspondence / 一致性

THEORY_CODE
  principle / mechanism / theory / 原理 / 机制
  AND implementation / source / code / 当前实现
  AND compare / relate / 对照 / 结合

DIAGNOSIS
  failure / error / fallback / validation / config / 异常 / 失败 / 配置
  AND reason / path / behavior / propagation / diagnosis / 原因 / 路径 / 诊断
```

优先级为 Change/Test、Docs/Code、Theory/Code、Diagnosis。Diagnosis 只有在
同时出现跨文件、传播、调用链等 generic relation signal 时才使用
`DIAGNOSIS_CROSS_FILE_V1`，否则使用单文件 profile。没有命中的一般问题使用
`NO_ADDITIONAL_REQUIREMENT`；不能按 repository、path、SHA 或 benchmark ID
路由。

## 2. Typed requirement 和 public evidence

`EngineeringEvidenceRequirement` 是 frozen dataclass。它保存 profile、
AND-of-OR 的 `required_evidence_groups`、最小 distinct code path 数和
`router_version`。创建后不能由模型、API 或 evaluator 覆盖。

`EvidenceRequirementState` 也是 immutable 的 shape-only 结果。它只统计当前
public evidence 的五种 kind：

```text
knowledge
project_code
project_doc
project_change
project_test
```

外层 evidence group 全部必须满足，组内任意一种 kind 即可满足。例如 Theory
要求 `knowledge`，以及 `project_code` 或 `project_doc`；Change/Test 要求
`project_change` 和 `project_test`；Docs/Code 要求两者都存在。跨文件
Diagnosis 还要求至少两个 distinct `project_code` source paths。

这个 evaluator 不看 snippet 内容、答案、问题、Gold 或语义相关性。两个路径
只能证明最低结构形状，不自动证明正确调用链。`changed_files` 仍可作为
candidate provenance，但不是 public evidence，不能替代 `project_test`。

## 3. Guard 插入 Runtime 的位置

唯一的完成闸门在 `FinalAnswerAction` 之后、Runtime 创建 `completed` 结果
之前：

```text
FinalAnswerAction
  -> 没有 requirement：沿用 Legacy
  -> 有 requirement：评估 public evidence shape
       -> satisfied：completed
       -> insufficient：block 或 system refusal
```

Guard block 不执行 Tool，也不消耗 Tool call；它只记录一个安全的
`finalization_guard_blocked` trace event，保存 evidence fingerprint，并让
下一次正常 Decision 看到受限的 recovery control state。真正的 Tool 仍只能
由模型 Action 请求，仍受原来的 5 / 4 / 2 budget 和 registry 约束。

## 4. 为什么 iteration 4 不能恢复

当前 Runtime 的最后一次 Decision 不允许执行 Tool。因而在
`max_agent_iterations = 5` 时，iteration 4 收到 insufficient final 即使还有
Tool call 配额，也不能 block 后推进到 iteration 5 再假装可以读取 evidence。
只有下一个 Decision 仍满足：

```text
iterations + 1 < max_agent_iterations
AND tool_calls < max_tool_calls
AND tool-errors budget remains
AND registry has a producer for a missing evidence kind
```

否则立即返回 system-owned 的
`INSUFFICIENT_EVIDENCE_TO_FINALIZE`。

## 5. Trusted missing-evidence state

Guard block 后，Engineering v2 的 system message 可以看到以下 bounded
Runtime metadata：

```text
finalization_blocked
missing_evidence_groups
current_distinct_project_code_paths
required_min_distinct_project_code_paths
```

它是 system-managed trusted control state，不是用户输入，也不是 Tool
Observation。里面不含 profile、task family、path、answer、question、Gold、
snippet、Prompt 或 CoT。Requirement 满足后，control state 恢复原来精确的五个
budget 字段，不把 recovery 字段留在普通 Decision 中。

## 6. Fingerprint 和 no-progress

fingerprint 只使用 public identity：Engineering evidence 的 kind、relative
path 和 bounded line location；Knowledge evidence 的 kind、source name 及
`chunk_id`，缺失时使用 rank。它不 hash 答案、snippet、问题、Gold 或原始
Tool payload，并且是确定性、与顺序无关的内部值。

第一次 insufficient final 会阻止完成并保存 fingerprint。下一次如果 evidence
仍不足且 fingerprint 未变化，即使答案文字换了，也直接 system refusal，避免
`Final -> Final` 空转。若先取得了新的 public evidence，fingerprint 改变，且
budget 和 producer 仍可恢复，则允许下一次 bounded block。

## 7. System refusal 和 legacy 边界

`INSUFFICIENT_EVIDENCE_TO_FINALIZE` 是 Runtime/system termination code，结果
为 `status="refused"`、`answer=None`、`failure_code=None`。它加入
`AGENT_TERMINATION_CODES`，没有加入模型可生成的 `REFUSE_REASON_CODES`，所以
模型不能伪造这个系统理由。

`ToolAgentRuntime.run(question)` 仍传入 `evidence_requirement=None`，完全走
原有 Legacy 行为：直接 final 仍可 completed，原有 refuse、parse failure、
duplicate Tool、Tool execution 和 5 / 4 / 2 语义不变。只有公开的
`EngineeringAgentFacade.run(question)` 做一次 system-side Router，再把
immutable requirement 传给 Runtime；API/evaluator 没有 requirement override。

## 8. Guard 不是 semantic verifier

Guard 只回答一个结构问题：是否有最低公开证据形状。它不会判断证据是否真的
支持 claim，也不会替代 Evidence Coverage、Evidence Correctness、Claim
Grounding 或 Manual Gold。因而“shape 足够但语义不对”和“答案语义较好但形状
不足”仍可能分别出现；System C 只能在后续 Formal 中验证它是否改善了
Premature Finalization 和 Evidence Sufficiency。

本次 System C tested factor 只有：通用 typed Evidence Requirement 加上
system-level Finalization Guard。Prompt v2、Prompt SHA、Repair、1200 cap、
5 / 4 / 2、7 Tools、provider/model 和知识库均未改变。生产代码也不 import
evaluator metadata。

当前状态是 `G12-04C = IN PROGRESS / IMPLEMENTATION REVIEW PENDING`，
`System C Formal = NOT RUN`；本任务完成后停止，待 Reviewer Audit。
