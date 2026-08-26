# 119. G12 Typed Requirement 与 Finalization Guard

这篇笔记解释 G12-04B 的设计。它不是代码实现，也不是 System C 的实验
结果。当前 System C Formal 仍然没有运行。

## 1. 问题从哪里来

Baseline A 已经证明：Agent 可以返回一个结构化完成结果，但“完成”不等于
“已经取得回答所需的证据”。例如某个 Change/Test 问题可能已经有
`project_change`，却没有读到测试源码；某个 Diagnosis 问题可能只读了一个
文件，却需要跨文件传播证据。

因此需要把下面两件事分开：

```text
模型认为自己可以回答
        !=
系统允许它宣布 completed
```

Typed Requirement 描述最低证据形状，Finalization Guard 在最后一步检查这个
形状。它不是语义裁判，不能自动判断答案是否正确。

## 2. 三层职责

未来的控制流是：

```text
用户问题
  -> Engineering Requirement Router
  -> immutable Evidence Requirement
  -> ToolAgentRuntime
  -> Decision / Tool loop
  -> FinalAnswerAction
  -> Finalization Guard
```

Router 负责从一般工程问题识别一个 bounded profile；Runtime 负责执行预算、
证据状态和终止规则；Guard 只负责在完成前检查不可变 requirement。这里不
需要第二个 Agent、Critic LLM 或 verifier LLM。

## 3. 为什么 Requirement 必须是 typed 和 immutable

如果模型自己报告“我需要哪些证据”，它可以在证据不足时降低自己的标准。
所以 requirement 由 system-side generic logic 创建，创建后只读传递给
Runtime。模型的 Action 不能替换它，evaluator Gold 也不能作为它的来源。

最小字段包括：

```text
requirement_profile
required_evidence_groups
min_distinct_project_code_paths
router_version
```

`task_family` 如果保留，只能用于内部 diagnostic，不能进入模型可见请求。
未匹配的一般问题使用 `NO_ADDITIONAL_REQUIREMENT`，这样不会把所有问题都
强行套进 G12 四类任务。

## 4. 四类 profile 的最低形状

证据组使用 AND-of-OR：外层每一组都必须满足，内层任意一个 kind 即可满足
该组。

| 场景 | `required_evidence_groups` | cross-file 最小路径 |
|---|---|---:|
| Theory <-> Code | `[[knowledge], [project_code, project_doc]]` | 1 |
| Change Impact <-> Test | `[[project_change], [project_test]]` | 0 |
| Diagnosis 单文件 | `[[project_code]]` | 1 |
| Diagnosis 跨文件 | `[[project_code]]` | 2 |
| Docs <-> Code | `[[project_doc], [project_code]]` | 1 |

两个 `project_code` 路径只能证明“形状上看过两个来源”，不能证明这两个
文件真的构成调用链。相关性、正确实现区域、Gold obligation 覆盖和最终
claim grounding 仍由 Manual Gold 判断。

## 5. Router 能看什么

Router 只能读原始 user question，做有界、确定性的 Unicode normalization、
case folding、空白和标点处理。它不能：

- 读取 benchmark、Gold、case ID、commit SHA 或 source path；
- 读取 Tool observation、仓库内容或 Agent answer；
- 调用 LLM、Knowledge、code search、embedding 或外部 NLP；
- 为某个固定题目、仓库文件名或 `g12q`/`g12c` 编写分支。

例如 Change/Test 要同时出现变更/commit/diff 类信号和 test/regression 类
信号；Docs/Code 要有文档、当前代码和一致性语义；Theory/Code 要有原理/机制、
实现和对照语义；Diagnosis 要有故障/配置/运行行为和原因/传播语义。发生
重叠时固定优先级为 Change/Test、Docs/Code、Theory/Code、Diagnosis。

跨文件 Diagnosis 还必须出现“调用链、跨模块、caller/callee、传播”等一般
关系信号，不能因为 Gold 里有两个路径或 Tool 调用了两次就推断出来。

## 6. Evidence 不是 candidate provenance

G12 当前公开 evidence taxonomy 只有：

```text
knowledge
project_code
project_doc
project_change
project_test
```

`changed_files` 可以帮助发现候选测试、记录候选来源、统计 change-set
membership，但它不是 public EngineeringEvidence。因此：

```text
candidate provenance != test behavior evidence
```

不能把 `changed_files` observation 偷换成 `project_test`，也不能把 evaluator
信息伪装成 Guard 可以消费的 evidence。未来若要改变这一点，必须先设计
受控、公开、typed 的产品 evidence 表示。

## 7. Sufficiency 只看 shape

可以把检查抽象成：

```text
evaluate_evidence_requirement(requirement, public_evidence)
```

它只检查 kind/count、AND-of-OR 组，以及需要时 distinct relative path count。
例如：

```text
[[knowledge], [project_code, project_doc]]
```

表示 `knowledge >= 1` 且 `project_code >= 1 OR project_doc >= 1`。

它不自动理解 snippet 是否相关，不知道实现 region 是否正确，也不知道
证据是否覆盖 Gold obligation 或支持答案里的具体 claim。故必须区分：

```text
Evidence Sufficiency = automatic structural metric
Evidence Coverage / Correctness / Claim Grounding / Task Success = Manual Gold
```

这也是为什么 `q004` 和 `q006` 都重要：前者 shape 足够但语义只有 PARTIAL，
后者 shape 不足但答案可以是 PASS。Guard 不能冒充语义 verifier。

## 8. Guard 在哪里工作

Guard 的唯一位置是 `FinalAnswerAction` 之后、Runtime 创建 `completed` 之前：

```text
FinalAnswerAction
  -> requirement + public evidence shape check
  -> sufficient: completed
  -> insufficient: block or bounded refusal
```

如果没有 requirement，保持既有 Legacy/Baseline 行为。如果有 requirement
且证据足够，正常完成。如果不足但仍有合适 Tool 和预算，Guard 阻止完成，
允许下一次正常 Decision；Guard 本身不消耗 Tool call，下一次 Decision 仍
消耗原有 iteration/provider 预算。

如果没有可恢复预算或没有可用 Tool，Runtime 返回 system-owned 的
`INSUFFICIENT_EVIDENCE_TO_FINALIZE`。这个 reason 不能由模型通过普通
`RefuseAction` 伪造，也不是自动把所有失败都算成 premature。

## 9. No-progress 规则

只要 Guard 阻止过一次，就记录一个 evidence fingerprint。它只包含 public
evidence 的 kind，以及安全的相对 source identity/path/bounded location。
它不包含 absolute path、Gold、私有 Tool payload、答案全文或 CoT。

下一次仍然证据不足且 fingerprint 不变时，停止恢复并返回系统拒绝；如果
fingerprint 发生变化，说明获得了新的 public evidence，在预算允许时还可以
继续一次 bounded recovery。这样既允许有效补证据，也不会因为同一个状态无
限循环。

硬限制依旧是 `5 / 4 / 2`。Guard 不会替 Runtime 增加预算，也不会自动执行
Tool。

## 10. Trusted control state 与 Prompt 边界

Prompt v2 和 SHA 完全不变。Guard block 后，system-managed control channel
可以给模型一个有限的恢复状态，例如：

```text
finalization_blocked
missing_evidence_groups
current_distinct_project_code_paths
required_min_distinct_project_code_paths
```

这是 trusted Runtime metadata，不是 user input，也不是 Tool Observation。
它不能暴露 task-family/profile、Gold、完整问题、原 rejected answer、snippet、
absolute path、Prompt 或 CoT。它只告诉模型缺少哪一类结构证据，不替模型写
答案，也不注入 benchmark 指令。

Safe Trace 可以增加 `finalization_guard_blocked`，但只记录 bounded iteration、
guard status、missing groups/kinds 和路径计数。未来 `guard_recovery_succeeded`
只有在“Guard 曾阻止 + 后续取得新 public evidence + 最终 requirement 满足”
时才为真；后面单纯 completed 不算恢复成功。

## 11. 反过度拟合与测试

实现测试应优先使用 synthetic non-benchmark query，覆盖：未匹配问题、优先级、
跨文件最小路径、AND-of-OR、无进展终止、legacy compatibility，以及
`completed AND evidence_sufficient=false` 不可能发生。

生产逻辑不能 import `evaluation.gate12`。如果实现发现必须修改 Prompt、读取
Gold 或增加 Tool，应该停下来重新评审 System C factor，而不是把设计偷偷扩
成 Prompt tuning 或 evaluator hack。

## 12. 面试式总结

可以这样解释这个设计：

> Agent 不是凭经验猜“我大概看过代码，所以可以完成”。系统先用不依赖
> benchmark Gold 的通用 Router 生成不可变证据要求，再由 Runtime 在最终
> 完成前检查公开证据形状。证据不够时，系统允许有限恢复或明确拒绝；它
> 不伪造证据，也不把 shape check 冒充语义理解。最终答案是否真的覆盖
> obligation、是否正确、claim 是否有依据，仍由 Manual Gold 判断。

G12-04B 的产物是这个设计契约，不是 Guard 实现。下一步为 G12-04C，当前
`System C Formal = NOT RUN`，`Finalization Guard = DESIGNED / NOT IMPLEMENTED`。
