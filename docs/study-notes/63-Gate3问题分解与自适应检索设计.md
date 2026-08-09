# 63 - Gate 3 问题分解与自适应检索设计

> G3-DESIGN-01：冻结 Gate 3 评测协议与架构契约（零业务实现）。本文是设计契约的学习笔记，非现状文档；实现状态以 `docs/status.md` 为准。
> 日期：2026-08-09
> 权威来源：主设计文档 `docs/design/g3_query_decomposition_adaptive_retrieval.md`；决策记录 `docs/adr/ADR-001-gate3-planning-routing-evidence-boundary.md`。

## 0. Gate 3 在回答什么问题

Gate 2 冻结了一个"简单检索就能很强"的基线（Recursive + BM25 top5 在 Benchmark v1 上是 winner）。Gate 3 不是"再上更高级的 RAG"，而是做一次**受控对照**：

> 在冻结语料上，有界 Query Decomposition 与 Adaptive Retrieval 是否比单次 BM25 primary 和 Hybrid control 带来可复现收益；收益是否值得额外的检索调用、Planner Token、延迟和失败风险？

三个关键词：

- **有界**：一切执行上限是冻结配置，不由模型决定（见 §4）。
- **受控**：只改变一个变量，其他全部冻结（见 §6 C/D 共享 snapshot）。
- **可复现**：身份（experiment_id / result_id / evaluation_set_id / corpus_id / snapshot）全部绑定，见 §3。
- **负结果有效**：如果 Decomposition 没有稳定收益，那就是 Gate 3 的正式结论。**"实现了高级 RAG"不是验收标准。**

## 1. 为什么必须同时保留两条 Baseline

Gate 2 的结论是 Recursive + BM25 是 winner，Hybrid 是 control。Gate 3 如果只跟 Hybrid 比，可能掩盖"简单 BM25 已经更强"；只跟 BM25 比，又观察不到融合策略行为变化。所以矩阵有四组：

| 组 | 策略 | Planner | Router |
|---|---|---|---|
| A | 原问题单次 BM25 | 无 | 固定 BM25 |
| B | 原问题单次 Hybrid | 无 | 固定 Hybrid |
| C | Decomposition + BM25 | 同一 snapshot | 子问题全 BM25 |
| D | Decomposition + Adaptive | 同一 snapshot | adaptive_rules_v1 |

A/B 不调用 Planner；C/D 用同一份 QueryPlan snapshot（见 §6）。E（Corrective Retrieval）默认不实现，满足第 13 节立项条件才做。

## 2. 为什么用独立实验配置，不扩展 Gate 2 ExperimentConfig

Gate 2 `ExperimentConfig` 是 frozen dataclass，experiment_id = 字段序序列化后 SHA-256 前 12 位。这个身份已经被 Gate 2 实验使用并冻结。Gate 3 要绑定的字段（Planner provider/model、prompt hash、temperature、max tokens、max subqueries、router policy、merge policy、fallback、timeout、corrective 开关）根本不属于"检索配置"域。

**原则**：实验身份绑定的是"配置语义"，不是"堆更多字段"。往已冻结的配置里塞新字段会改变既有 experiment_id 的语义，破坏 Gate 2 Artifact 的可复现绑定。所以 Gate 3 在 `evaluation/gate3/` 建立独立的 `Gate3ExperimentConfig`，有自己的 schema version。

## 3. 正式 Run ID 绑定了什么

Gate 3 正式 Run ID 至少绑定：

- Gate3ExperimentConfig ID（本身又绑定 planner/queryplan/route/evidence schema version、base retrieval、prompt hash、全部硬预算）；
- corpus_id（复用 Gate 2 冻结 `870e5864df67`，控制语料变量）；
- evaluation_set_id（G3-DATA-02 建立的 36 条新问题集）；
- split（dev / sealed holdout）；
- QueryPlan snapshot ID；
- 代码冻结 commit。

时间、路径、API Key、对象地址、latency、实际输出内容**不进**配置 ID。

## 4. 为什么硬预算不由 LLM 决定

表里这些数值是"不可变执行配置"：

| 项 | 值 |
|---|---|
| 每请求 Planner 调用 | 最多 1 次 |
| 最大子问题数 | 3 |
| 每子问题最长 / evidence_target 最长 | 1000 / 500 字符 |
| 最大 retrieval rounds / Retriever 调用 | 1 / 3 |
| 最终唯一文档数 | 5 |
| temperature / max output / timeout / 重试 | 0 / 800 tokens / 20s / 0 |
| Reranker / Corrective | false / false |
| 失败默认回退 | 原问题单次 BM25 |

**为什么**：一旦上限由模型输出控制，成本、时延、失败风险就成了模型行为的一部分，实验前无法冻结身份，A/B/C/D 也就无法对照。硬预算是"收益是否值得额外调用"唯一可测的前提。模型输出越界时**回退**到原问题单次 BM25，而不是截断后继续。

## 5. 为什么 QueryPlan / RouteDecision / EvidenceBundle 三层分离

- **QueryPlan**（`query_plan_v1`）：问题是什么、是否需要检索、是否需要分解、最多 3 个子问题。它**不允许**携带 selected strategy、candidate_k、final_k、reranker 开关、max retrieval rounds、Gold obligation ID、隐藏思维链。
- **RouteDecision**（`route_decision_v1`）：为原问题或某个子问题选 Retriever（`bm25` / `simple` / `hybrid`）。它不生成子问题、不判断 Gold、不承担实验编排。
- **EvidenceBundle**：保留 subquery → chunk → document 映射，去重、确定性合并成最终 Top-5 文档。

**为什么**：三个职责的失败模式不同（schema/分类问题 vs 策略选择问题 vs 证据丢失问题），分离后能独立验证、独立回退，且 `reason_code` 让每层决策可审计。

**策略名注意**：Dense Retriever 在代码里的正式策略名是 `simple`（`core/retriever/simple.py` 的 `SimpleRetriever`；`ExperimentConfig.VALID_RETRIEVER_STRATEGIES = ("simple","hybrid","mmr","bm25")`）。文档和配置必须沿用 `simple`，不能自造一个映射不到代码的 `dense` 值。

## 6. 为什么 C 和 D 必须共享同一份 QueryPlan snapshot

如果 C、D 各调用一次 Planner，LLM 两次输出的子问题可能不同，Router 对照就被"两次不同的规划"污染——你分不清收益来自 Router 还是来自更幸运的分解。共享 snapshot 让 C/D 成为**严格单变量对照**：只允许 Router 不同。

实现含义：规划阶段（Planner + QueryPlan 规范化）与检索阶段（Router + Retriever）解耦；正式运行先一次性生成并冻结 QueryPlan，再分别跑 C 和 D。

## 7. 为什么 Gate 2 的 50 条 Case 不能再当泛化证据

那 50 条 Case 已经被 Gate 2 全流程调参用过。任何基于它们的指标都带过拟合污染。Gate 3 建立**新的 36 条问题**（comparison 8 / multi_entity-multi-hop 6 / causal-synthesis 6 / troubleshooting 4 / simple-fact-code_symbol 6 / unanswerable 3 / no_retrieval 3），24 条进 dev、12 条进 **sealed holdout**（分层 split，holdout 至少 7 条多 evidence obligation）。

50 条旧 Case 降级为 regression suite：字节不变、允许开发期失败分析、**不计入 holdout**。

## 8. sealed holdout 的三层隔离纪律

目标：实现冻结之前，holdout 从未被读取过。

1. **物理隔离**：holdout 的 Query、Gold、逐 Case 结果存放在用户控制目录（`D:\学习\rag实战项目\rag数据集\benchmark_work\gate3\sealed\`），主仓库只登记 schema version、corpus_id、case_count、类型分布、SHA-256、evaluation_set_id、sealed 状态。
2. **时间隔离**：正式 holdout 运行前必须冻结代码 commit、Planner Prompt、provider/model、temperature、QueryPlan Schema、Router policy/threshold、merge policy、fallback、全部成本上限。实现 Agent 在编码/调参/Prompt 调整阶段不得读取 holdout。
3. **次数隔离**：holdout 原则上只正式运行一次；看到逐 Case 结果后继续调规则 → 该 holdout 立即失效，必须新建 evaluation_set_id。

**核心**：读取 holdout 后调整规则 = 用测试集拟合。这不是流程洁癖，是"泛化证明"概念上的唯一可靠来源。

## 9. Merge Policy v1：subquery_round_robin_v1

合并规则（按序执行）：

1. 有效分解时不额外检索原问题；
2. 每个子问题独立检索；
3. 按 `sq1 → sq2 → sq3` 顺序，每轮各取一个尚未出现的文档；
4. 重复文档跳过；
5. 重复轮转直到 5 个唯一文档或候选耗尽；
6. 单个 Retriever 内沿用其既有稳定排序；
7. **不直接比较 BM25、Dense、RRF 的原始分数**；
8. 输出必须确定性。

第 7 条很关键：跨 Retriever 的原始分数不可比，所以轮转合并只依赖"文档身份 + 各自内部稳定排序"，不依赖跨通道分数比较。

## 10. Dev 晋级与 holdout 保留是工程 Gate，不是统计学结论

任务卡把晋级条件写成**可操作的工程门槛**（如：C 晋级需要 schema validity ≥ 98%、fallback 后完成率 100%、不必要分解率 ≤ 10%、相对 A 的 obligation coverage 提高 ≥ 0.05、至少修复 3 个 full-obligation Case、full-obligation loss ≤ 1）。这些是"是否继续投入"的决策规则，样本规模小，**不能包装成普遍统计结论**。任何结论必须限定范围：仅该语料、该 evaluation set、该 holdout。

---

## 关键知识点速记

- Gate 3 是**受控对照**不是"高级 RAG 炫技"；负结果也是正式结论。
- 实验身份 = 配置语义的哈希绑定；扩展冻结配置 = 破坏既有身份。
- 硬预算是不可变执行配置；模型输出越界 → 回退单次 BM25，不截断。
- Dense 正式策略名是 `simple`，不是 `dense`。
- C/D 共享 QueryPlan snapshot，保证 Router 单变量对照。
- holdout 三层隔离（物理/时间/次数）；看到结果再调规则 = 失效。
- 50 条旧 Case 只作 regression，不证明 Gate 3 泛化。
- `subquery_round_robin_v1`：轮转去重合并，不跨通道比较原始分数。
