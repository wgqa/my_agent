# 128 — Unified Runtime Adaptive Retrieval Migration

> ARCH-RETRIEVAL-05：把 G3 的计划检索能力接入 Unified Engineering Runtime，
> 但保持 Single Engineering Agent、one trusted control state、one logical budget owner。

## 1. Plan 与 plan execution 的边界

`ARCH-PLAN-04` 只把一次可信的 `PlannerOutcome / QueryPlan` 接入主链；那时
`action`、`query_type`、`subqueries` 和 `retrieval_required` 还是 passive planning
state。`ARCH-RETRIEVAL-05` 才允许这份 Plan 驱动有限的 Knowledge Retrieval execution。
Plan execution 不是第二个 Agent，也不是让 Planner 自己循环调用工具。

顺序固定为：

```text
Context Resolver
  → Evidence Planner
  → Requirement Router
  → Adaptive Retrieval Policy
  → Knowledge Retrieval Execution
  → Evidence Merge
  → planned evidence handoff
  → ToolAgentRuntime
```

## 2. Adaptive Retrieval

Adaptive Retrieval 是一个确定性的 route policy：它根据 trusted `query_type`、
`action` 和 backend capability 选择 `direct`、`single_retrieval`、
`decomposed_retrieval` 或 `no_retrieval`。它只产生有限调用计划，不拥有
`RetrievalBudget`、retry loop、replanning 或 finalization。

冻结边界是 `top_k=5`、`max_retrieval_calls=4`、
`adaptive_retrieval_policy_v1`、`subquery_rrf_merge_v2`、`merge_rrf_k=60.0`。

## 3. fact / code_symbol → BM25

对 `fact` 和 `code_symbol`，Frozen G3 route 的 primary strategy 是 BM25。
这是可解释的 lexical path，适合精确术语、类名、方法名和配置名。只要 primary
有结果，就不再升级到 Hybrid。

生产 Knowledge backend 当前可能只暴露 BM25 capability；此时复杂单问的
Hybrid 意图必须 capability-fallback 为 BM25，而不是伪造一个不存在的 Hybrid
调用或引入第二个 Retriever controller。

## 4. complex single → direct Hybrid

复杂的 single retrieval 在支持 Hybrid 时直接使用 Hybrid primary。它不先跑
BM25 再比较，也不额外做 Dense call；这样一次策略选择就能使用既定 Hybrid
候选链路。若 backend 不支持 Hybrid，route 会选择可用的 BM25 fallback，并
保持调用上限。

## 5. 一次 BM25 empty rescue

single route 若 primary 是 BM25 且结果为空、同时 backend 支持 Hybrid，只允许
一次 Hybrid rescue。若 BM25 已返回证据，不 rescue；若 Hybrid 也为空，不再重试。
因此 single 总调用数最多 2，且 rescue 是确定性的 policy branch，不是异常重试。

## 6. 最多三个 subquery

decomposed retrieval 只执行现有 `QueryPlan` 的 2 或 3 个 subquery，保持
`sq1 → sq2 → sq3` 顺序。每个 subquery 的 primary 是 BM25；缺失结果时只给
第一个缺失 subquery 一次 Hybrid rescue。不能生成第四个 subquery，不能重写
QueryPlan，也不能因为结果为空重新规划。总调用数最多 4。

## 7. Multi-query ≠ Multi-Agent

Multi-query 是同一个 Agent 的 Evidence Backend 执行策略：一个已冻结的 Plan
产生多个有限查询，最后汇总为一个 EvidenceBundle。它没有自己的身份、Prompt、
budget ledger、stop/refusal、finalization 或 autonomous loop，因此不能被叫作
Multi-Agent。

## 8. RRF merge v2

多 subquery 结果使用既有 `merge_subquery_results_policy` 和
`SUBQUERY_RRF_MERGE_V2`，`rrf_k=60.0`，最终最多 5 个 evidence item。合并
保留确定性排序、去重、citation/provenance、`query_id` 和 bounded output。
同一个 chunk 在不同 subquery 出现时，以融合策略产生一个稳定 item，而不是
把重复证据交给模型。

## 9. 不做 cross-subquery raw BM25 比较

不同 subquery 的 BM25 raw score 不保证可直接比较：查询长度、词项和候选分布
不同，数值不在同一尺度。系统不拿 raw score 跨 query 排名；每个 query 先
保留自己的 rank，再由 RRF v2 按 rank 融合。这样更可解释，也避免把 backend
分数误当成跨查询置信度。

## 10. Internal EvidenceBundle 与 public KnowledgeEvidence

内部 G3 `EvidenceBundle` 是 trusted control state，保留 `EvidenceItem`、
`query_id`、retrieval-call count、query count、rank、score 和 provenance。
它不直接暴露给 API、Prompt、Trace 或 Activity。对 ToolAgent 的 handoff 只做
严格、fail-closed 的 conversion，生成现有 public `KnowledgeEvidence`：
`kind=knowledge`、安全相对 `source_name`、保留 `chunk_id`、有限 snippet（≤500）、
有限 score 与 `rank≥1`。

绝对路径、危险 provenance、完整文档、Gold、Prompt 和 CoT 均不能通过转换。
转换失败应在 Provider/ToolAgent 执行前失败，而不是伪装成空证据。

## 11. 为什么必须保留 query_id

`query_id` 是子查询证据的身份与可审计连接。single 证据绑定 resolved input，
decomposed 证据绑定 `sq1`/`sq2`/`sq3`；RRF merge 不得把它丢掉。后续 verifier、
citation 和诊断需要知道某个证据来自哪一个计划查询，不能只保留一个无法解释的
全局列表。

## 12. Planned evidence seed

Retrieval 完成后生成 bounded `DecisionContextItem` 与 `KnowledgeEvidence`，
通过内部 adapter 在 ToolAgent 第一个 Decision 前注入。模型看到的是安全、截断
的知识匹配和 observation-like context，不看到 raw document、Planner object、
Prompt、Key、绝对路径或 CoT。planned evidence 同时参与现有 G12 requirement
evaluation，保持一套 evidence state。

## 13. 为什么禁用第二个 knowledge_search

如果 planned retrieval 已经完成，Engineering 同一 run 再开放
`knowledge_search`，模型可能重复检索、绕过 QueryPlan、改变调用上限或形成第二
个 Knowledge policy。Engineering registry 因此在该 run 过滤 `knowledge_search`；
ToolAgent 仍负责 Repository/Git/Test 等后续工具。legacy `/tool-agent/query`
保持原 registry 与行为，避免破坏 legacy endpoint 回归。

## 14. Retrieval component 不是 Agent loop

`EngineeringRetrievalComponent` 只有有限的 route → port call → merge → conversion
流程。它没有 LLM Decision、ToolCall parser、Observation loop、独立 budget、
failure recovery controller 或终止决策。ToolAgentRuntime 继续是唯一的 LLM
Decision → Tool → Observation loop；它在迁移期执行原有 5/4/2 hard enforcement，
但只是 Unified Runtime 的 execution component，不是第二个 Agent。

## 15. MinimalEvidenceVerifier 当前不迁移

本阶段不调用或复制 `MinimalEvidenceVerifier`，也不迁移 Grounded Generation、
Finalization Policy、Citation Validator。它们保留在历史 G3/G12 能力边界中，待
`ARCH-VERIFY-06` 等后续阶段在同一 Verification/Finalization owner 下处理。当前
成功证明的是 planned retrieval handoff 与 legacy ToolAgent 兼容，不是 verifier
或最终答案质量已经完成统一。

## 16. 两分钟面试讲法

> 我们没有把 G3 AgentRuntime 套在 ToolAgentRuntime 外面。ARCH-PLAN-04 先把
> QueryPlan 作为可信计划接入，ARCH-RETRIEVAL-05 再把 Adaptive / Multi-query
> Retrieval 迁移成一个有限 Evidence Backend component：fact/code symbol 走
> BM25，复杂单问在支持时直接走 Hybrid，BM25 空结果最多一次 Hybrid rescue，
> 多 subquery 用 RRF v2 合并且最多 3 个 query、4 次调用。内部保留 G3
> EvidenceBundle 和 query_id，转换成 bounded KnowledgeEvidence 在第一个
> ToolAgent Decision 前注入，并禁用第二个 knowledge_search。这样仍是一个
> Engineering Agent、一个可信控制状态、一个逻辑 budget owner；Verifier 和
> Finalization 留到后续阶段，避免 big-bang rewrite 和 nested controller。
