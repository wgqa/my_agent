# 124. G12 最终收口与核心 Agent 完成

## 1. Gate 12 为什么可以关闭

Gate 12 的目标不是把某一项干预调到满分，而是完成一次可审计的
Engineering Evaluation 2.0 研发闭环。这个闭环已经依次完成：

1. 两个独立代码仓库上的冻结 16-case benchmark；
2. 已冻结的 Baseline A；
3. 一个最小、deterministic 的 typed Evidence Requirement 与 Finalization Guard；
4. 在同一 benchmark 上的 A/C Formal；
5. 逐 case 的 Manual Gold；
6. 接受真实的正、负或 invalid 实验结果，而不因结果重跑或修改规则。

最终有效 System C run 为
`g12-system-c-formal-manual-20260826-203236`。它绑定
`gate12-v1-630fc8b527c2`、最终 benchmark SHA
`630fc8b527c22d3e7afc4f4288788524f5dfb52f5ed6ade13ec050abc35f215f`、
System C product `65ee45eb52c45e95d2871aa9060416dabcd3d759` 与 acceptance
contract SHA `5a9d190dcb585a29097fac206c14aa0f31c27d178d8fe0cae8d72b1b8c17bb8f`。
最终 closure baseline 是 `299632e6d78c1a0fb83f32c7dea7be70cc53e9fd`。

因此 Gate 12 的正式状态是 `CLOSED / FROZEN`，当前核心 Agent 项目阶段的状态是
`CORE AGENT SYSTEM = COMPLETE`。

## 2. 最终实验结论

Baseline A 的 Manual Gold 为 Task Success `PASS=2 / PARTIAL=8 / FAIL=6`，
Evidence Sufficiency 为 `2/16`，Premature Finalization 为 `12/16`，Claim
Grounding 为 `PASS=1 / PARTIAL=8 / FAIL=7`。

System C 的 Manual Gold 为 Task Success `PASS=2 / PARTIAL=7 / FAIL=7`，
Evidence Sufficiency 为 `2/16`，Premature Finalization 为 `9/16`，Claim
Grounding 为 `PASS=1 / PARTIAL=5 / FAIL=10`。System C 的 final classification 是
`VALID / FAIL`，不是 infrastructure invalid。

结论必须准确表述为：Evidence-Grounded AI Engineering Agent 的核心架构、工具面、
评测协议、跨仓库 transfer benchmark 与实验闭环均已完成。Baseline 显示系统具有
mixed task capability，但 evidence-grounded reliability 仍弱；最小 deterministic
Finalization Guard 的实现机械正确且真实发生过 intervention，但单独依赖该 Guard
并未在 transfer benchmark 上产生预期的可靠性提升。

这不表示 Guard 的 Runtime 状态机实现失败，也不表示整个项目失败。它表示预先冻结的
“最小 Guard 单独改善 reliability”假设没有得到支持。Gate 12 接受这个 negative
result 并冻结，不进行 benchmark-aware Router patch 或结果选择式 rerun。

## 3. COMPLETE 的含义与边界

`COMPLETE` 不等于没有缺点，不等于所有 benchmark PASS，也不等于产品已经达到
生产级成熟度。它表示当前规划中的核心研发闭环已经完成，并且已经用真实实验识别了
剩余技术债。

这个核心阶段已经交付：

- 知识证据检索；
- 真实代码仓库导航；
- Git change evidence；
- 测试定位；
- Diagnosis / Config 与 Docs <-> Code 工作流；
- 受控 Tool Agent loop、bounded runtime 与 safe trace；
- Evidence Sufficiency evaluation 与 Manual Gold；
- 跨仓库 transfer benchmark；
- typed Finalization Guard。

被冻结为未来工作的技术债包括：Requirement understanding / routing recall、Evidence
planning、Evidence relevance、cross-file evidence acquisition、test evidence acquisition、
claim-evidence grounding 与 tool-loop reliability。

这些是下一轮增强的候选输入，不是本次冻结后自动修复的待办。**No automatic Gate 13.**
若未来继续，可独立立项 Evidence Planning 2.0、semantic requirement routing、
Graph-based planning、multi-agent 或 GraphRAG；它们是新一轮能力增强，不是为了“修复
G12 成绩”。这条边界避免让 frozen benchmark 变成反复调规则的训练集。

## 4. Provider incident 与实验有效性

两次早期 System C Formal 分别为
`g12-system-c-formal-20260826-173039` 和
`g12-system-c-formal-r1-20260826-191531`。它们均为
`INVALID / PROVIDER-PLANE FAILURE`，底层观测为 `APIConnectionError`，不用于 Agent
能力结论。

可复现性记录只能写成：

> Agent-managed execution environment showed reproducible APIConnectionError, while manually launched equivalent API processes succeeded.

人工 PowerShell 启动等价 API 的 health 为 PASS，随后以相同人工进程完成了有效的
16-case Formal。不能把这个事实夸大成“Codex sandbox definitely blocks networking”。
产品失败与 infrastructure invalidity 必须分开，才不会把执行环境异常冻结成产品负结果。

## 5. 以后的真实实验执行规则

对需要真实网络、Provider、完整服务进程或长时间 Formal experiment 的工作，默认由
操作者在普通本机 Shell 启动。执行 Agent 负责生成命令、代码、测试和 artifact 分析。
当执行环境异常时，先区分 Product Failure 与 Infrastructure Invalidity，再决定是否能
形成能力结论。

这是一条实验工程经验，不是新的产品 Runtime contract。它既保留了执行环境的可审计性，
也避免把临时基础设施问题误写成模型或产品能力问题。
