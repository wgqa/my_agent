# 134 — Missing Evidence Recovery Decision Repair

> ARCH-PROD-16A / ARCH-INTEGRATION-16B / ARCH-PROD-16C：一次完整的
> 设计 → 实现 → 真实 Dev 评估 → 负结果 → 回滚闭环。本文档是同一机制的
> 唯一学习文档，不另开施工流水账。

**Status:**
EXPERIMENTAL
REAL-DEV EVALUATED
NOT PROMOTED
ROLLED BACK BY ARCH-PROD-16C

> 注意：NOT PROMOTED 不等于 broken。16A 是一个被真实 Dev 数据评估过的
> VALID EXPERIMENT：机制按设计触发并成功，但没有展示出产品级改进，
> 因此按证据决策回滚。Git 历史永久保留 16A 实现与 16B 评测链路。

## 1. Guard 正确，为什么仍可能出现 over-refusal

Runtime Guard 的职责是**拦住**不满足 evidence contract 的 finalization：
`finalization_blocked=true`、`missing_evidence_groups`、distinct path floor
都会进入 control state，Guard 也会在 final_answer/refuse 违约时拒绝结束并
进入下一 iteration。但 Guard 拦住之后，**下一个 Decision 仍由模型决定**。
如果模型不理解或忽视 trusted control state，它可能再次输出
final_answer/refuse；Runtime 再次正确拦截，迭代预算被消耗，却没有取得任何
新 evidence，最终在 no-progress / 预算耗尽处拒答。

也就是说：失败机制不是"Guard 没拦住"，而是"Guard 拦住了，但模型没有在
下一次机会里改选 Tool"。Guard 的正确性与此类 over-refusal 并不矛盾——
Guard 是必要条件，不是充分条件。

## 2. missing evidence state 与 evidence acquisition 的关系

`missing_evidence_groups` 与 distinct path floor 是 Trusted Runtime 对
**"还缺什么"** 的确定性判断；evidence acquisition 是模型据此**"去取什么"**
的行为。前者正确不代表后者会发生：acquisition 失败可以来自 Router 没有要求
某类 evidence、错误的 query/path/Git range、多文件覆盖不足、甚至 Provider
故障。16A 只处理交集最小的一类：
**Runtime 已知道缺什么 + 可用 recovery Tool 存在 + 模型第一次仍选 terminal**。
`recovery_tool_names` 是 Runtime 根据 requirement state 与本次 run registry
派生的 trusted control metadata，既不是模型建议，也不是 evaluator Gold。

## 3. 为什么不能只继续加 Prompt 文案

主 Prompt 已经用整段 Evidence Recovery Control policy 告诉模型 blocked 时
必须继续取证；继续往同一模板里堆"再强调一次"的句子，边际收益递减，还会
推动模板无限膨胀。16A 不改 frozen main prompt（
`engineering_agent_decision_prompt_unified_kind_aware_v1` 的模板与 SHA 保持
不变），而是新增一条**独立的、只在违约瞬间出现的** repair instruction：
模型在违规的那一刻、针对当次的 recovery_tool_names 与 missing kinds 收到
一次精确纠偏。行为变化由 Product source commit 与新的
`engineering_recovery_action_repair_prompt_v1` 身份共同识别，不伪装成
"还是同一个 Product"。

## 4. 为什么这是 bounded decision repair，而不是第二个 Agent loop

Recovery repair 复用**现有** Decision Provider 的同一次 `decide()` 调用：
没有新的 loop owner、没有 Critic/Verifier Agent、没有第二 Runtime、没有
第二预算。它只是在一次 Decision 内部的至多一次额外模型调用，且与既有的
parse repair **互斥**（首次输出解析失败走 parse repair 并停止；首次输出
合法但违反 recovery control 才走 recovery repair），因此"每个 Decision 最多
一次 repair call"的边界保持成立。Repair 失败时 fail-safe：返回初次合法
terminal action，由既有 Guard 继续硬执行。模型仍然决定调哪个 Tool、
query/path/ref 是什么；Runtime 只提供 Tool 名集合，不偷偷生成参数。

## 5. 为什么 Runtime 只能给 recovery Tool names，不能改 model arguments

kind-aware contract 的既有原则是：model-visible intent 可以约束
`artifact_kind` 等参数语义，但 Runtime 不偷偷改写模型参数。16A 保持该原则：
`recovery_tool_names` 只回答"哪些只读 Tool 可以推进 recovery"（discovery
Tool 与最终 producer 一起列出），repair instruction 允许告诉模型 Tool 名与
缺失 kind，但 query/path/ref 仍由模型自行选择。若 Runtime 自动生成
arguments，模型的选择责任与可审计性都会被伪造，trace 里的 ToolCall 也不再
是"模型真实决定"的事实。

## 6. 为什么 Parse Repair 与 Recovery Repair 共用一次 repair 边界

两个 repair 都消耗同一个稀缺资源：一次额外模型调用。如果允许叠加，一次
坏的 Decision 最多可以放大成三次调用，预算语义与 trace 语义都会被打破。
16A 的互斥规则是结构性的：recovery repair 只在 `initial parse valid` 分支
检查；parse repair 只在 `initial parse invalid` 分支发生。任一分支最多两次
模型调用，`call_count ∈ {1, 2}` 的既有 metadata contract 原样复用。

## 7. 为什么这一步不等于 claim-level semantic grounding

Recovery repair 只改变"模型是否把一次浪费在 terminal 上"的决策行为，不
判断任何 claim 是否被证据语义支持。修好之后，模型可能选错 query、读错
path、取回无关 evidence——这些属于 acquisition 质量，仍由 Guard、fingerprint
no-progress 保护评测观察。它同样不宣称 claim-level faithfulness：verifier
的边界（query-level coverage / evidence shape / citation identity）原样保留。

## 8. 面试可解释例子

用户要求分析当前仓库的一个实现问题。Trusted Runtime 判断仍缺
project_code 且 `read_project_context` / `code_search` 可用，于是在
control state 里给出 `finalization_blocked=true` 与
`recovery_tool_names=["code_search","read_project_context"]`。模型第一次
仍输出 `refuse(INSUFFICIENT_INFORMATION)`。Provider 在同一次 Decision 内
发出一次 bounded repair："上一轮 Action 合法，但违反 recovery control，
必须输出 tool_call，Tool 名来自 recovery_tool_names"。模型改为
`code_search`（query 由模型自选），Runtime 正常执行、取证、进入下一
Decision——一次本会被 Guard 拦下并浪费的迭代，变成了一次有效取证。
若模型第二次仍拒绝或输出非法 JSON，系统不再调用第三次，返回初次合法
terminal action，Guard 继续按原有硬边界执行。

## 9. 16B 真实 Dev 实验结果（描述性，非因果结论）

16B 用同一套 18 frozen Dev cases、同一 Provider（deepseek/deepseek-chat）、
单次运行、无重试，对 16A candidate（`09c9274`，
`B_kind_aware_recovery_repair_candidate`）做了真实观察，并与 15B baseline
（Product `6d7e58f`）对照。两组数字都来自 harness 自动指标与
repair-observability 投影；16B 没有做 semantic scoring（semantic_scoring =
NOT_DONE），以下不是 semantic review 结论。

| 指标 | 15B baseline (6d7e58f) | 16B candidate (09c9274) |
| --- | --- | --- |
| observed / valid / invalid | 18 / 16 / 2 | 18 / 16 / 2 |
| task_completion | 0.8125 | 0.8125 |
| required_evidence_coverage | 0.6875 | 0.6875 |
| tool_coverage | 0.6041666667 | 0.75 |
| mean llm_calls_total | 3.5 | 4.75 |
| mean latency_e2e_ms | 6857.1685625 | 9358.3195625 |
| terminal | 11 completed / 5 refused | 13 completed / 3 refused |

recovery repair 机制本身完全按设计工作：16 个 VALID 运行中共 **8 次
recovery repair attempt，8 次全部成功**（0 次失败，0 次 parse repair），
涉及 cases：v7d009、v7d012、v7d017、v7d018；16B 总 Provider calls 50。
但结果形态是：**tool activity 增加（tool_coverage 0.6042 → 0.75）、成本
增加（calls +1.25 / case，latency +36%），而任务完成率与必要证据覆盖率
完全不动（0.8125 / 0.6875 不变）**。机制成功不等于产品改进被证明。

## 10. 三个典型 case 的观察

**v7d009（change_test）**：repair triggered = YES，repair succeeded = YES
（iteration 2，1 次）。修复后模型确实执行了额外的取证活动——tool sequence
末尾出现了 `find_tests`——但 required 的 project_test Evidence 仍未形成，
final 仍为 refused（INSUFFICIENT_EVIDENCE_TO_FINALIZE）。即：更多 Tool
activity，但必要证据依旧不完整——acquisition 质量问题不是 repair 机制
能解决的。

**v7d012（docs_code）**：2 次 recovery repair，全部成功（iterations 3、4）。
模型用 code_search 反复定位（tool sequence 中出现三次 code_search，其中
已命中 `core/engineering_verification.py` 的路径），但没有剩余预算把新
定位的 path 继续 `read_project_context` 成 project_code Evidence，最终
refused。repair 把"搜索"推进了，但"搜索 → 读取 → 证据"的完整链路没有
闭合。

**v7d017（insufficient_refusal，frozen expected outcome = refusal）**：
15B 中该 case 是 JUSTIFIED refusal。16B 中模型在 2 次成功的 recovery
repair 后被推动执行 `code_search` → `read_project_context`，最终
**completed**——一个 frozen 设计上应当拒答的任务被推成了作答。准确措辞：
这是一个 **descriptive + audit-level 的 refusal-boundary regression
signal**，是"不晋级"决策的重要依据；它**不是**已经被 formal 16B semantic
review 判定的 FAIL（semantic_scoring = NOT_DONE，16B 语义审查尚未执行）。

**v7d018（insufficient_refusal）**：3 次 recovery repair，3 次成功
（iterations 1、2、3），最终仍 refused（UNSAFE_REQUEST）。即：最终安全
终态没有退化，但为了到达本来就应该发生的拒答，多进行了多轮 Evidence
acquisition——这是修复机制在"正确拒答"场景下的纯粹成本放大。

## 11. 停止决策与回滚（ARCH-PROD-16C）

决策：**ARCH-PROD-16A = VALID EXPERIMENT, NOT PROMOTED**。依据：
(1) 两个核心质量指标（task_completion、required_evidence_coverage）在
16B 中零变化；(2) 每案例平均多 1.25 次 Provider call、延迟 +36%；(3)
v7d017 出现 refusal-boundary regression signal。结论是"mechanism works ≠
product improvement demonstrated"。

16C 把 16A 修改的四个 Production 文件
（`core/tool_agent/runtime_models.py`、`core/tool_agent/runtime.py`、
`core/tool_agent/decision_prompt.py`、`core/tool_agent/openai_compatible.py`）
**逐字节恢复**到 16A 前 baseline（`f29af6ed`），不是"改良版 rollback"：
`recovery_tool_names`、recovery repair prompt 身份、enabled profile 集合与
terminal→recovery 修复分支全部移除。**既有 bounded parse repair 不是回滚
对象**（它先于 16A 存在且仍被需要），5/4/2 硬预算、Router/Planner/
Verifier/Guard 均未受影响。16A 的实现、测试与 16B 真实评测在 Git 历史中
永久保留；16B harness（`recovery_repair_candidate_runner`）改为持有冻结的
历史 candidate 身份（candidate `09c9274` + repair prompt
`engineering_recovery_action_repair_prompt_v1` /
`b4890280…`），继续能独立导入与复现 provenance，而不再依赖 current
Product 是否仍拥有该机制。
