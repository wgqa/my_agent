# 134 — Missing Evidence Recovery Decision Repair

> ARCH-PROD-16A：当 Trusted Runtime 已经确认 evidence contract 未满足、
> Recovery Tool 实际可用，而 Decision Model 第一次仍输出 premature terminal
> action 时，允许同一个 Decision Provider 在**同一次 Decision 内**做至多一次
> bounded recovery repair，要求模型改为合法 ToolCall。Guard、预算与
> Single Engineering Agent 架构全部不变。

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
故障——这些都不是 16A 的对象。16A 只处理交集最小的一类：
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
terminal action，由既有 Guard 继续硬执行——最坏情况退化为 16A 之前的行为，
而不是引入一条秘密执行路径。模型仍然决定调哪个 Tool、query/path/ref 是
什么；Runtime 只提供 Tool 名集合，不偷偷生成参数。

## 5. 为什么 Runtime 只能给 recovery Tool names，不能改 model arguments

kind-aware contract 的既有原则是：model-visible intent 可以约束
`artifact_kind` 等参数语义，但 Runtime 不偷偷改写模型参数。16A 保持该原则：
`recovery_tool_names` 只回答"哪些只读 Tool 可以推进 recovery"（discovery
Tool 如 code_search/find_tests/changed_files 与最终 producer 一起列出），
repair instruction 允许告诉模型 Tool 名与缺失 kind，但 query/path/ref 仍由
模型根据用户问题与既有 Tool observations 自行选择。若 Runtime 自动生成
arguments，模型的选择责任与可审计性都会被伪造，trace 里的 ToolCall 也不再
是"模型真实决定"的事实。

## 6. 为什么 Parse Repair 与 Recovery Repair 共用一次 repair 边界

两个 repair 都消耗同一个稀缺资源：一次额外模型调用。如果允许叠加，一次
坏的 Decision 最多可以放大成三次调用，预算语义与 trace 语义都会被打破。
16A 的互斥规则是结构性的：recovery repair 只在 `initial parse valid` 分支
检查；parse repair 只在 `initial parse invalid` 分支发生。任一分支最多两次
模型调用，`call_count ∈ {1, 2}` 的既有 metadata contract 原样复用，
recovery repair 的 `initial_parse_category=None` 也是该 contract 已允许的
形状，不需要新增 repair provenance 字段。

## 7. 为什么这一步不等于 claim-level semantic grounding

Recovery repair 只改变"模型是否把一次浪费在 terminal 上"的决策行为，不
判断任何 claim 是否被证据语义支持。修好之后，模型可能选错 query、读错
path、取回无关 evidence——这些属于 acquisition 质量，仍由 Guard、fingerprint
no-progress 保护和后续评测（16B）观察。它同样不宣称 claim-level
faithfulness：verifier 的边界（query-level coverage / evidence shape /
citation identity）原样保留，16A 没有引入任何 semantic 判断。

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

## 9. 状态与边界（16A 范围声明）

已实现：`recovery_tool_names` trusted 字段与 canonical recovery mapping、
registry 交集（disabled Tool 不复活）、OR-group 并集、distinct path floor、
kind-aware profile opt-in 的单次 recovery repair、repair metadata 复用、
synthetic 测试。**机制已实现不等于效果已验证**：真实表现（是否减少
over-refusal、是否提高 acquisition 成功率）必须由后续 16B 的真实运行验证，
16A 不声称任何评测结论。
