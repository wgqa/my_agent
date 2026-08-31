# 129 — Unified Runtime Evidence Verification

> ARCH-VERIFY-06：把 retrieval coverage、G3/G12 evidence checks 与 citation-ID
> validation 收敛为一个 trusted result，并保持 Single Engineering Agent、one
> trusted control state、one logical budget owner。

## 1. Evidence found 不等于 evidence sufficient

检索到一条资料、命中一个路径、Tool 已 completed，最多说明 evidence found。
它不自动说明证据满足当前问题的结构要求，也不说明最终 claim 已被语义证明。
Sufficiency 必须由明确的 requirement、coverage 与 verification state 共同表达。

## 2. Retrieval sufficiency 与 pre-merge coverage

复杂问题的 sufficiency 不能只看最终 merge 后有几个 item。`q0`、`sq1`、
`sq2`、`sq3` 是计划查询的 identity；required/covered truth 在 RRF merge 前由
各 query 的最终结果记录。RRF 去重后保留的 representative item 只有展示/证据
身份意义，不能代表整个 subquery coverage。

因此 decomposed retrieval 即使合并后只有一个 representative item，只要每个
required subquery 在 merge 前有结果，coverage 仍然完整；反过来，缺失的
`sq2` 不能因为 `sq1` 的 item 被 merge 保留下来而被掩盖。

## 3. MinimalEvidenceVerifier 的角色

G3 `MinimalEvidenceVerifier` 是 query-level 的 retrieval/coverage check，复用
现有 `VerificationResult`。在 ARCH-VERIFY-06 中它由
`EngineeringEvidenceVerifier` 调用，并接收 snapshot 保存的 required/covered IDs。
它不做 claim-level semantic verification，不是一个独立 finalizer，也不拥有
Tool loop、budget 或 refusal state。

## 4. G12 requirement 的角色

G12 `evaluate_evidence_requirement` 检查 typed public evidence 的 shape：例如
Theory ↔ Code 的 knowledge 与 project evidence，或 Diagnosis 的 cross-file
distinct project paths。它回答“要求的 evidence kind/path shape 是否满足”，不
回答“文本是否语义蕴含答案”。G12 state 被纳入同一个 verification result。

## 5. 一个 verifier、一个 result

`EngineeringEvidenceVerifier` 只编排三种已有检查：G3 retrieval result、G12
requirement state、CitationValidator result，并返回一个不可变
`EngineeringVerificationResult`。`can_finalize` 是 retrieval 可生成、G12
满足、citation 非 INVALID 三者的合取；ToolAgent 的现有 finalization point
只消费这一个 trusted result。

不允许 G3、G12、Citation 各自拥有一套 completed/refused 决策，也不允许外层
AgentRuntime 再包一层 finalization controller。

## 6. CitationValidator 的边界

现有 `CitationValidator` 只检查答案中的 `[C#]` 是否存在于本次 EvidenceBundle
适配出的 ContextBlock。它不检查 claim 是否被内容 entail，也不运行 LLM judge，
所以不能把 citation-ID valid 写成 semantic grounding verified。

答案没有 citation 时状态为 `NOT_PRESENT`，这是非阻塞的；答案尚未产生时为
`NOT_CHECKED`；所有引用存在时为 `VALID`；任一引用不存在时为 `INVALID`，并
阻止 finalization。

## 7. Recovery boundary

G12 缺少 Repository/Git/Test evidence 时，如果已有 producer Tool、剩余
5/4/2 预算和 iteration 条件都允许，ToolAgent 可以进行下一次既有 Decision，
补充 evidence 后重新计算同一个 verifier result。恢复不新增 loop、budget 或
controller。

planned Knowledge Retrieval insufficiency、incomplete subquery coverage 和
invalid citation reference 不属于可恢复的 G12 evidence shortage。它们直接使用
既有 `INSUFFICIENT_EVIDENCE_TO_FINALIZE` hard stop；不得重新启用
`knowledge_search`，不得加 citation-repair LLM。

## 8. Counters 与 observability

Verification 是纯检查，不增加 ToolAgent iteration、tool call 或 tool error。
Safe Trace / Rich Activity 只记录旁路事实，observer failure 不能改变
completed/refused/failed outcome。5/4/2 仍由迁移期的 ToolAgent execution
component hard-enforce；逻辑上仍只有一个 Budget Owner。

## 9. 两分钟面试讲法

> ARCH-VERIFY-06 没有重写 G3/G12 算法，而是把它们和 CitationValidator 放到
> 一个 `EngineeringEvidenceVerifier` 中，输出一个 `EngineeringVerificationResult`。
> Retrieval coverage 必须在 RRF merge 前按 `q0/sq1…` 记录，不能被 representative
> item 的 query ID 掩盖。G12 缺少 repo/test evidence 时可以在原 5/4/2 内走下一次
> Tool；planned retrieval 不足和 invalid citation 直接 hard stop。ToolAgentRuntime
> 仍是执行组件，不是第二个 Agent；最终只有一个逻辑 budget owner 和一个
> finalization seam。

## 10. 常见错误设计

- 把“有一个 evidence item”当成所有 subquery 都覆盖；
- 用 RRF representative `query_id` 反推 merge 前 coverage；
- 让 `MinimalEvidenceVerifier`、G12 Guard、CitationValidator 各自决定 final；
- 把 citation-ID 存在误写为语义 entailment 或 claim grounding；
- 为 invalid citation 增加 repair LLM，或为 planned retrieval 不足重新开
  `knowledge_search`；
- 外层 `AgentRuntime` 套 `ToolAgentRuntime`，产生两个 loop、两个 ledger 或
  两个 stop/refusal owner；
- 为了接入 G3 一次性重写 runtime，或把当前未完全 cutover 当成永久废弃 G3。

## 11. 迁移原则

ARCH-VERIFY-06 是 component migration：保留 Gate 1～G12 frozen facts、Gate 2/3
sealed/formal 结论、G12 question-only contract、legacy endpoint regression 和
public API/SSE shape；不改 Prompt、Router、5/4/2、Formal、Persistence 或
Citation UI。最终 control-plane cutover 仍由 ARCH-CUTOVER-07 单独处理。
