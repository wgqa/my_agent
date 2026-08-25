# Engineering Evaluation 2.0 与 Evidence Sufficiency

## 1. 为什么 G11 之后还要做 G12

G11 已经覆盖了 Theory <-> Code、Change Impact <-> Test、Diagnosis / Config、Docs <-> Code 四类真实工程任务，但结论不能写成“Agent 已经会做工程分析”。四类任务反复出现同一个缺口：Agent 有时找到了文件、调用了正确 Tool，甚至返回了 completed，却没有拿到足以支持最终结论的证据。

G11-02 是跨源理论与代码的 claim-level grounding debt；G11-03 是 change evidence 可以到位而 test evidence 不足；G11-04 是 cross-file diagnosis 与 structured action 都不稳定；G11-05 则说明只读文档或只读代码的一侧，不能支持 Docs <-> Code 的确定性判断。G11-04、G11-05 的 Manual Gold 都是 0/4。

因此 G12 不是“再写一个更长的 Prompt”，而是把证据、最终回答与工程正确性拆开测量，并研究一个最小的系统级 finalization guard 是否真的有帮助。

## 2. 什么叫 Evidence Sufficiency

Evidence Sufficiency 不是 evidence 数量大于零，也不是 Tool 调用次数足够。它是针对任务类型的最低证据契约。

```text
找到文件
    != 读到相关 source window
    != 证据覆盖了问题
    != 最终 claim 被证据支撑
    != 工程结论正确
```

例如，Docs <-> Code 的结论至少同时需要文档原文和当前代码；只读 README 不能推出 implementation 当前仍然如此，只读代码也不能推出 README 实际写了什么。Theory <-> Code 至少需要知识证据与实现相关 repository evidence。涉及跨文件传播的 Diagnosis，必须读到传播两端，而不是用一个配置文件猜调用方行为。

G12 冻结的 public evidence kinds 不变：`knowledge`、`project_code`、`project_doc`、`project_change`、`project_test`。不新造“看起来像证据”的指标种类。

## 3. 四类任务的最低证据契约

| Task family | Minimum evidence |
|---|---|
| Theory <-> Code | `knowledge` + `project_code` 或 `project_doc`；语义 relevance 仍由 Manual Gold 判断 |
| Change Impact <-> Test | `project_change` + `project_test`；test filename 本身不等于 test behavior evidence |
| Diagnosis / Config | `project_code`；`requires_cross_file=true` 时至少要有 2 个 distinct `project_code` paths |
| Docs <-> Code | `project_doc` + `project_code`；没有 pair 不得做确定性 consistency label |

这些 group 采用 AND-of-OR 语义：外层每一组都必须满足，内层任意 evidence kind 可以满足该组。例如 Theory <-> Code 是 `[[knowledge], [project_code, project_doc]]`，即必须有 `knowledge`，且必须有 `project_code` 或 `project_doc`；Docs <-> Code 是 `[[project_doc], [project_code]]`；Change Impact <-> Test 是 `[[project_change], [project_test]]`；Diagnosis 是 `[[project_code]]`。

### changed_files candidate 为什么不是 public evidence

`changed_files` 很有用，但当前只能说明 change-set membership 或提供 candidate discovery/provenance，例如“某个推荐测试是否已在 changed set 中”。它的 observation 不会进入当前 Runtime 的 public evidence taxonomy，因此不能假装成 `project_test`，也不能自动满足 Change Impact <-> Test 的 Evidence Sufficiency。

这正是 G11-03 的 test evidence debt：candidate provenance != test behavior evidence。要知道测试真正验证什么，仍需要 `read_project_context(test)` 产生的 `project_test`。若未来希望把 changed-files-derived candidate 变成 Guard 可消费 evidence，必须先单独设计受控、公开、typed evidence representation；evaluator 不能私下把 Tool observation 升级成 Runtime 没有的 evidence kind。G12 v1 不做这个改变。

### 为什么 automatic Sufficiency 只能测 shape

自动 Sufficiency 只检查 public evidence kind、minimum count、AND-of-OR group structure，以及必要时的 distinct source/path count。它不判断 snippet 是否相关、implementation region 是否正确、Gold obligation 是否被覆盖、evidence 是否支持某条 final claim，或 final label 是否正确；这些分别是 Evidence Coverage、Evidence Correctness、Claim Grounding 和 Task Success，全部继续由 Manual Gold v1 评估。

cross-file 的最小 shape 也因此是 distinct path count，而不是“调用了两次 Tool”：同一文件读两次不能证明两端 source 都已获取。`requires_cross_file=true` 时至少两个 distinct `project_code` paths 才满足结构下限，但两个文件仍不等于 propagation reasoning 正确。

这个契约只回答“是否已经具备最小 finalization shape”。它不自动证明答案正确，也不能代替人工检查某个 source window 是否真的覆盖了 Gold obligation。

## 4. G12 要测的不是一个分数

G12 的核心指标包含 Task Success、Evidence Sufficiency、Evidence Coverage、Evidence Correctness、Claim Grounding、required/forbidden Tool coverage、Premature Finalization、Structured Action Failure 和 Duplicate Tool Stop。

其中 evidence kinds、evidence pair、path hit、Tool 调用、预算、延迟、parse/repair 等可以先自动统计；答案是否真的正确、具体 claim 是否有正确 source 支撑、remediation 是否合理、跨文件传播是否成立，仍然是 Manual Gold。这种保守分工比让 runner 假装理解所有工程语义更可信。

`completed` 也不是正确。它只表示 Runtime 完成了响应协议。一个 completed case 仍可以 evidence 不足、结论错误，或 claim 超过实际读到的窗口。

## 5. Finalization Guard 是什么假设

当前行为可以简化为：

```text
FinalAnswerAction -> completed
```

G12 的候选系统机制是在真正 completed 前检查不可变的任务证据要求：

```text
FinalAnswerAction
    -> Evidence Contract Check
    -> sufficient?
       yes -> completed
       no  -> continue once within existing budgets,
               or return structured incomplete/refusal
```

它不是第二个 LLM，不看 Gold，不认识 DOC01/DC03，不按问题字符串或文件名放行，不会生成答案，也不会扩大 5/4/2 budget。它只能用“这个任务需要哪些 evidence group”和“Runtime 已经得到哪些 public evidence”决定能否 finalization。

`INSUFFICIENT_EVIDENCE_TO_FINALIZE` 只是未来实现的候选名称，当前没有代码、reason code 或产品行为变化。

## 6. 为什么 Requirement 不能让模型自己决定

如果让模型在准备回答时自报“这题只需要一份代码”，它可能为了完成而把 Docs <-> Code 或 cross-file diagnosis 降级成单侧任务。这样 guard 只会执行模型自己降低后的标准。

G12 比较了三个方向：LLM self-report、deterministic query classifier 和 hybrid typed requirement。推荐的是第三种：系统/router 产生一个有界 typed requirement，Runtime 只消费 immutable value。它保留了可审计的系统边界，同时不把所有自然语言任务都硬塞进脆弱的纯规则分类器。

候选结构只是一份 architecture contract：`task_family`、`required_evidence_groups`、`requires_cross_file`、`min_distinct_project_code_paths`、`allows_knowledge_only`、`allows_repo_only`。`min_distinct_project_code_paths` 默认是 1，`requires_cross_file=true` 时不得低于 2。G12-01 不定义 production class。

## 7. Duplicate 与 Parse 不是同一种失败

G11 中有 `AGENT_DUPLICATE_TOOL_CALL`，也有 `ARGUMENTS_SCHEMA_INVALID` 和 repair 0/1。它们不应被混成“evidence 不足”。

| Layer | 典型问题 |
|---|---|
| L1 Structured Transport / Parsing | action JSON 或 arguments 不合法，repair 失败 |
| L2 Planning / Tool-loop | duplicate call、wrong tool、budget misuse |
| L3 Evidence Acquisition | 只有 locator、漏读第二 source、没有 bilateral pair |
| L4 Reasoning / Grounding | 无证据的 propagation、错误 consistency judgment、overclaim |

当前 duplicate 是 safety hard stop。未来可比较保留 hard stop 与“一次有界 recovery decision”，但都不能重复执行 Tool、不能扩 budget。这个问题与 Finalization Guard 分开实验，避免一个机制的结果混入另一个机制。

## 8. A/B 怎么才算公平

G12 计划至少比较三组：

| Arm | Configuration |
|---|---|
| Baseline A | 当前 Engineering v2 Prompt + 当前 Runtime |
| Control B | 未来若授权的 Prompt-only control |
| System C | 与 A 相同 Prompt + system-level Evidence Finalization Guard |

三组必须使用相同独立 benchmark、project commits、evaluator isolation、provider/model identity、budget、registry、output cap 和 artifact-safety policy，除非这些正是被测变量。System C 不能只报告“完成更多”，还必须报告 evidence sufficiency、claim grounding、premature finalization、refusal、Tool/provider calls、latency、parse/repair、duplicate stop 和 budget stop。

预期方向是 System C 的 Evidence Sufficiency 与 Claim Grounding 上升，Premature Finalization 下降，且 Task Success 不显著下降。具体阈值必须先运行独立 Baseline A 后、查看 C 前冻结，不能先拍一个好看的百分比。

## 9. 为什么 evaluator isolation 是正式协议的一部分

G11-05 的首次 Formal 曾发生 repository leakage：evaluator Study Note、runner、test metadata 与被评测项目在同一 searchable checkout，DOC03 实际引用了 Study Note 112。该 run 虽然 4/4 HTTP 完成，却是 `INVALID / EVALUATION CONTAMINATION`，不能得出能力结论。

所以 G12 的每次 Formal 都要分开记录 `evaluator_commit` 和 `project_source_commit`，保证两个 clean checkout 的 resolved root 不同，并检查 evaluated project tree 没有 evaluator-owned Gold files。评测基础设施可信，不代表 Agent 能力已经通过；但基础设施不可信时，能力结论也不成立。

## 10. 面试时怎么解释 G12

可以这样说：

> 我没有把“模型调用了代码搜索”当成工程任务成功。G11 的真实 Formal 显示，Agent 常能定位文件，却没有读到足以支持最终结论的代码、测试或文档窗口。G12 因此把 evidence presence、sufficiency、coverage、correctness、claim grounding 和 task success 分层测量，并用独立 checkout 防止 Gold 泄漏。下一步会比较 Prompt-only 与系统级 finalization guard：guard 不生成答案，只在系统准备 final 时检查是否已拿到该类任务最低所需的公开证据。

这说明项目关注的不只是 Agent “会不会调用 Tool”，还关注评测是否独立、失败属于哪一层、系统机制是否真的优于 Prompt-only 约束。

## 11. 当前边界

G12-01 只冻结 protocol 和 Evidence Sufficiency contract。它没有实现 verifier、guard、critic、multi-agent、GraphRAG、semantic code index 或新 Tool，没有调整 Prompt 或 5/4/2 budget，没有创建 G12 benchmark，没有选择/下载 external repository，也没有运行 real-provider Formal。

G12-02 才会处理 dataset 与 repository freeze。G12 完成前，Core Agent System 仍是 NOT COMPLETE。
