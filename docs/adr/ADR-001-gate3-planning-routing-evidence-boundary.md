# ADR-001：Gate 3 Query Planning / Adaptive Routing / Evidence 边界

> ADR 状态：**Accepted — decision prescribed by project reviewer**
> 日期：2026-08-09
> 关联设计文档：`docs/design/g3_query_decomposition_adaptive_retrieval.md`（G3-DESIGN-01 主文档）
> 权威来源分层：本 ADR 记录 Gate 3 架构决策与理由；冻结数字以 `docs/experiments/gate2_freeze.json` 为准；实时状态以 `docs/status.md` 为准。

本 ADR 记录 G3-DESIGN-01 冻结的 8 个架构决定与 6 个被拒替代方案。所有决定都由项目审查者（project reviewer）在 Gate 3 设计契约中指定，执行 Agent 不做架构取舍，只负责把契约写成可执行、可验证的文档。

---

## 决定 D1：QueryPlan / RouteDecision / EvidenceBundle 三层结构分离

**决定**：Gate 3 将规划、路由、证据合并拆分为三个独立契约层：

- `QueryPlan`（Schema `query_plan_v1`）只描述"问题是什么、是否需要检索、是否需要分解、最多 3 个子问题"，不携带任何检索策略、候选 k、重排开关或 Gold 信息。
- `RouteDecision`（Schema `route_decision_v1`）只描述"为原问题或某个子问题选哪个 Retriever"，绑定一个已规范化的 QueryPlan。
- `EvidenceBundle` 只描述"每个子问题的命中如何被保留、去重、确定性合并成最终 Top-5 文档"。

**理由**：
- 三个职责的变化频率与失败模式不同：规划层失败是 schema/分类问题；路由层失败是策略选择问题；合并层失败是证据丢失问题。分离后每一层都可以独立验证、独立回退。
- QueryPlan 一旦生成，必须能跨多个实验组复用（C 与 D 共用同一份 snapshot）；如果把路由或合并逻辑混进 QueryPlan，共享 snapshot 就失去意义。
- 可解释性：`reason_code` 枚举让每一层的决策都能被审计，而无需把自由文本推理塞进配置身份。

**后果**：实现时 `core/query_planning/`、`core/adaptive_retrieval/`、`core/evidence/` 三个目录各司其职，禁止跨目录混放业务逻辑。

---

## 决定 D2：执行上限由不可变执行配置控制，不由 LLM 决定

**决定**：最大子问题数（3）、每子问题字符（1000）、evidence_target 字符（500）、retrieval rounds（1）、Retriever 调用次数（3）、最终唯一文档数（5）、Planner temperature（0）、max output（800 tokens）、timeout（20s）、自动重试（0）、Reranker（false）、Corrective Retrieval（false）全部是**不可变执行配置**。任何模型输出都不能突破这些上限，也不能要求模型"决定"这些上限。

**理由**：
- 一旦上限由 LLM 输出控制，成本、时延、失败风险就变成模型行为的一部分，无法在实验前冻结身份。
- 硬预算是"可复现对照"的前提：A/B/C/D 四组共享同一套预算，差异只来自策略本身。
- 有界性本身就是 Gate 3 的研究对象——"收益是否值得额外检索调用与失败风险"只有在有界预算下才可测。

**后果**：Planner 输出越界时，回退为原问题单次 BM25（`single_bm25_original_query`），而不是截断后继续。

---

## 决定 D3：使用独立 `Gate3ExperimentConfig`，不扩展 Gate 2 `ExperimentConfig`

**决定**：Gate 3 实验配置在 `evaluation/gate3/` 下建立独立的 `Gate3ExperimentConfig`，其身份至少绑定 config schema version、QueryPlan/RouteDecision/EvidenceBundle schema version、frozen base retrieval config、planner mode/provider/model、prompt version/hash、temperature、max tokens、max subqueries、router policy、fallback、merge policy、final_k、max rounds/calls、timeout、corrective 开关。Gate 2 `ExperimentConfig` 的现有身份语义（frozen dataclass，experiment_id = 字段序序列化 SHA-256 前 12 位）保持不变，继续只服务 Gate 2 检索实验。

**理由**：
- Gate 2 `ExperimentConfig` 是冻结的、已生成稳定 experiment_id 的契约。扩展它会改变既有实验身份的语义，破坏 Gate 2 Artifact 的可复现绑定。
- Gate 3 需要绑定的字段（Planner、Router、Merge、fallback 等）根本不属于 Gate 2 检索配置域，硬塞进去会污染两个 Gate 的身份含义。

**后果**：Gate 3 有自己独立的 config schema version 与实验 ID 生成规则；`gate2_freeze.json` 中登记的 experiment_id/result_id 一律不改。

---

## 决定 D4：BM25 primary 与 Hybrid control 同时保留为 Gate 3 Baseline

**决定**：Gate 3 必须同时保留两个冻结 Baseline：
- **A：BM25 primary**（`dbc497c796d5` / `acd92171966d`，recursive + cl100k_content_v1 + bm25 + top5）作为主基线；
- **B：Hybrid control**（`3c613202e1ed` / `e27141a2b63e`）作为对照基线。

Gate 3 在新 evaluation set 上重跑相同配置时生成**新的 Gate 3 Run Artifact**，不得覆盖 Gate 2 Artifact。

**理由**：
- 只与 Hybrid 比较可能掩盖"简单 BM25 已经更强"的事实（Gate 2 结论：Recursive+BM25 是 Benchmark v1 winner）；只与 BM25 比较又无法观察融合策略行为变化。
- 两条基线让 Gate 3 既能回答"Decomposition 是否击败最强简单策略"，也能回答"Adaptive Retrieval 相对固定 Hybrid 是否有净收益"。

**后果**：实验矩阵包含 A（BM25）、B（Hybrid）、C（Decomposition+BM25）、D（Decomposition+Adaptive）四组对照；E（Corrective）默认不实现。

---

## 决定 D5：C 与 D 复用同一份规范化 QueryPlan snapshot

**决定**：C（Decomposition + BM25）与 D（Decomposition + Adaptive Retrieval）的正式对照必须复用**同一份规范化 QueryPlan snapshot**，只允许 Router 这一变量不同。

**理由**：
- 若两次分别调用 Planner，LLM 输出的子问题可能不同，Router 对照就被"两次不同的规划"污染——无法区分收益来自 Router 还是来自更幸运的分解。
- 复用 snapshot 使 C/D 成为严格单变量对照：只有 `adaptive_rules_v1` 路由这一变量变化。

**后果**：规划阶段（Planner + QueryPlan 规范化）与检索阶段（Router + Retriever）解耦；正式运行时先一次性生成并冻结 QueryPlan，再分别跑 C 与 D。

---

## 决定 D6：Gate 2 的 50 条 Case 只作 regression suite，不计入新 holdout

**决定**：Gate 2 原有 50 条 Case 字节保持不变，继续作为 regression suite，允许用于开发期失败分析；**不得**计入新的 sealed holdout，**不得**继续当作 Gate 3 泛化证明。Gate 3 新增 36 条问题（G3-DATA-02 建立），24 条进 dev、12 条进 sealed holdout（分层 split，holdout 中至少 7 条多 evidence obligation）。

**理由**：
- 50 条 Case 已经被用于 Gate 2 全流程调参，任何基于它们的"指标"都带有过拟合污染，不能作为新策略的泛化证据。
- 泛化证明必须来自实现冻结之前从未被读取过的 holdout；把旧 Case 算进 holdout 是数据泄漏。

**后果**：holdout 的 Query、Gold 与逐 Case 结果在正式评测前不得提交主项目仓库；主仓库只登记 schema version、corpus_id、case_count、类型分布、SHA-256、evaluation_set_id、sealed 状态。

---

## 决定 D7：holdout 内容在实现冻结前隔离于主仓库之外

**决定**：实际 holdout 的 Query、Gold 和逐 Case 结果存放于用户控制目录 `D:\学习\rag实战项目\rag数据集\benchmark_work\gate3\sealed\`。实现 Agent 在编码、路由调参和 Prompt 调整阶段不得读取 holdout 内容；正式 holdout 运行前必须冻结代码 commit、Planner Prompt、provider/model、temperature、QueryPlan Schema、Router policy/threshold、merge policy、fallback、全部成本上限；holdout 原则上只正式运行一次；若看到 holdout 逐 Case 结果后继续调规则，该 holdout 立即失效，必须新建 evaluation_set_id。

**理由**：
- 读取 holdout 后调整规则 = 用测试集拟合，任何后续指标都不再能证明泛化。
- 物理隔离（独立目录）+ 时间隔离（实现冻结后运行）+ 次数隔离（只跑一次）三层纪律，是这一防线唯一可靠的实现方式。

**后果**：G3-DATA-02 建立问题集时即完成 holdout 生成与 SHA-256 登记；G3-EVAL-08 只在冻结后运行一次 holdout。

---

## 决定 D8：ExperimentRunner 不承载 Planner / Router / Evidence 业务逻辑

**决定**：现有 `ExperimentRunner` 继续只承担 Gate 2 检索实验编排（prepare → index_corpus → run_retrieval → compute_retrieval_metrics → finalize_result）。Planner、Router、Evidence 合并逻辑**不得**堆入 `ExperimentRunner`。

**理由**：
- `ExperimentRunner` 及其 Artifact（retrieval_results.json / retrieval_metrics.json / result.json）是 Gate 2 已冻结的、有稳定实验身份的产物。往它里面塞 Gate 3 的 LLM 规划与路由逻辑，会破坏 Gate 2 Artifact 的契约与可复现性。
- Gate 3 有独立编排路径（`evaluation/gate3/`），其失败分类（PLAN_*/ROUTE_*/RETRIEVAL_*/OBLIGATION_*/MERGE_*/BASELINE_REGRESSION/…）与 Gate 2 的单阶段失败模型不同。

**后果**：Gate 3 实现新增独立 orchestration 层；`ExperimentRunner` 代码零改动（仅被 Gate 3 以"frozen base retrieval"方式复用其确定性检索事实）。

---

## 被拒替代方案

| # | 被拒方案 | 理由 |
|---|---------|------|
| R1 | 用单个 LLM 黑盒同时做规划 + 路由，不产生结构化中间产物 | 无法跨实验组共享 snapshot；无法用 `reason_code` 审计决策；无法区分"规划失败"与"路由失败"，违背 Gate 3 的可解释性与失败分类要求 |
| R2 | 只保留 Hybrid 作唯一 Baseline | 掩盖"简单 BM25 已经更强"（Gate 2 winner 是 Recursive+BM25）；无法判断 Adaptive 相对最强简单策略的净收益 |
| R3 | 继续用 Gate 2 的 50 条 Case 证明 Gate 3 泛化（算进新 holdout） | 已被 Gate 2 全流程调参使用，带有过拟合污染；作为 holdout 是数据泄漏，不构成泛化证据 |
| R4 | 把 Gate 3 字段直接加进 Gate 2 `ExperimentConfig` | 改变已冻结的 experiment_id 身份语义，破坏 Gate 2 Artifact 的可复现绑定；跨域字段混入一个检索配置结构 |
| R5 | 把所有 Planner/Router/Evidence 逻辑直接堆进 `ExperimentRunner` | 破坏 Gate 2 编排契约与 Artifact 稳定性；单阶段失败模型无法表达 PLAN_*/ROUTE_*/MERGE_* 等 Gate 3 失败类型 |
| R6 | 让模型自由决定检索轮数和子问题数量 | 上限一旦由 LLM 决定，成本/时延/失败风险不可在实验前冻结，无法做受控对照；硬预算是"收益是否值得额外调用"唯一可测前提 |
