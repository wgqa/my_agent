# 74-Gate3自适应检索Dev对照实验

> G3-ADAPT-06B：在公开 Dev 24 Case 上，用同一份冻结 Planner 输出与冻结 37 文件语料、同一份共享新建索引，完成四组真实检索对照（A/B/C/D）。
> 日期：2026-08-13
> run_id：`4d29b9e0b2cc`；source_commit：fb295dd；corpus：870e5864df67（37 files）；Dev：f2144030d754（24 Case）；Planner run：497808269bdd。
> 权威来源：实现 `evaluation/gate3/adaptive_dev.py`、`scripts/run_gate3_adaptive_dev.py`、`tests/test_gate3_adaptive_dev.py`；外部 Artifact `benchmark_work/gate3/adaptive_dev_runs/4d29b9e0b2cc/`（不入 Git）。
> 范围声明：只评估检索/证据覆盖/路由/调用成本；不调用真实 Planner、不调用 Generator（C/D 用 No-op AnswerPort）、不做答案正确性评测；不读 Holdout。

---

## 0. 结论先行（诚实结果）

**Decomposition + Adaptive 在这个 Dev 集上没有跑赢单次原问题 BM25，反而更差，且贵一倍。**

| 指标 | A 原问题BM25 | B 原问题Hybrid | C Plan+BM25 | D Plan+Adaptive |
|---|---|---|---|---|
| obligation 覆盖 | 36/44=0.818 | 36/44=0.818 | 32/44=0.727 | 32/44=0.727 |
| full coverage | 15/20=0.75 | 13/20=0.65 | 13/20=0.65 | 13/20=0.65 |
| multi-obligation 完整 | 11/16=0.688 | 9/16=0.563 | 9/16=0.563 | 9/16=0.563 |
| Hit@5 | 0.95 | 1.00 | 0.90 | 0.90 |
| Recall@5 | 0.842 | 0.833 | 0.783 | 0.783 |
| MRR | 0.875 | 0.904 | 0.775 | 0.775 |
| nDCG@5 | 0.805 | 0.815 | 0.738 | 0.738 |
| 检索调用总数 | 24 | 24 | 49 | 49 |

**C 与 D 完全一致**：冻结 Planner 把 Dev 里全部 16 条复杂语义题（comparison/causal/multi_entity/troubleshooting）都规划成了 decomposed_retrieval，策略表对 decomposed 一律 bm25，"complex single → hybrid" 分支在 Dev 上从未触发；也没有任何一次 BM25 空结果需要 Hybrid rescue（rescue used = 0）。所以 D 的"自适应能力"在这个数据集上根本没用上，D 退化成了 C。

## 1. 为什么复用 Planner snapshot

A/B/C/D 必须用**同一份冻结 Planner 输出**，否则四组的差异会混入"Planner 变了"这个变量。复用方法：

- 从 `dev_runs/497808269bdd/planner_results.jsonl` 读取每条记录；
- 用 `QueryPlan.from_dict()` 严格重建（不信任旧派生字段）；
- 校验 24 条 case_id 与 Dev 精确相等、query 与 Dev 一致、predicted 与重建 QueryPlan 一致；
- C/D 共用这同一份内存快照（SnapshotPlanner），**绝不重新调用 Planner**。

这样四组唯一的差异是"执行方式"，规划本身被冻结，实验才是受控对照。

## 2. A/B/C/D 控制变量

| 变量 | A | B | C | D |
|---|---|---|---|---|
| 用 QueryPlan？ | 否 | 否 | 是（冻结） | 是（冻结） |
| 检索 query | 原问题 | 原问题 | 子问题 | 子问题 |
| 初始策略 | bm25 | hybrid | bm25（能力强制） | adaptive（生产策略） |
| Hybrid rescue | — | — | 禁止 | 最多一次 |
| Generator | 无 | 无 | No-op | No-op |

共享：同一份新建索引（recursive / cl100k / 512/64 / bge / dense30/sparse30 / rrf60 / chunk_id_asc / top_k=5 / reranker=false）、同一份语料、同一份 Dev、同一份 Planner 快照。C 用一个 `BM25OnlyCapabilityAdapter` 只向 Runtime 声明 `("bm25",)`，从而禁止 Hybrid 与 rescue；D 用生产 `PipelineRetrievalAdapter`。

## 3. obligation coverage 与 document recall 的区别

- **document recall / Hit / MRR / nDCG**：只看**文档级**——检索结果里的文档（去重后的 canonical 路径）是否命中 Gold `relevant_files`、命中位置。answerable 20 条上计算，unanswerable/no_retrieval 排除。
- **obligation coverage**：**义务级**——每条 obligation 的 `relevant_files` 是否被最终检索文件集命中至少一个（OR 语义）。一个 case 的所有 obligation 都命中才叫 full coverage。

document recall 问"该引的文档引到没有"，obligation coverage 问"每个必需方面有没有证据"——后者是 Gate 3 的评测核心，因为一个 multi-obligation 问题缺一个方面，答案就是残缺的。

## 4. 为什么不把 No-op Answer 当答案指标

C/D 必须走完 Runtime（规划→检索→合并→覆盖检查→生成）才能得到覆盖结论，但本任务**不评测答案**。所以注入确定性 No-op AnswerPort（`answer_generation=not_evaluated`、`answer_adapter=deterministic_noop`），返回固定 synthetic 字符串。**synthetic answer 不是答案**，绝不能当正确性指标；Artifact 里明确登记这两个字段，防止后续误用。

## 5. Decomposition / Adaptive 的真实收益

- **Decomposition（C 比 A）**：**没有收益，反而损失**。obligation 覆盖 0.818→0.727（-0.091，-5 条义务）、full 0.75→0.65、Hit 0.95→0.90、Recall 0.842→0.783、MRR 0.875→0.775。检索调用 24→49（+25，约 2 倍）。
  - 原因：子问题通常比原问题**短、词汇更窄**，BM25 对"详细的原始提问"召回更多 Gold 文档；round-robin 合并 + `max_evidence_items=5` 还会**丢弃候选**（candidate 覆盖 0.84 → merge 后 0.73，merge-drop 5 条义务）。
- **Adaptive（D 比 C）**：**完全一致**。冻结 Planner 把全部复杂语义题规划为 decomposed → bm25，hybrid 分支从未触发；没有 BM25 空结果需要 rescue。Adaptive 的潜在收益在 Dev 上没有样本可证明。
- **Hybrid 原问题（B 比 A）**：Hit@5 0.95→1.00、MRR 0.875→0.904 提升，obligation 覆盖持平（0.818），full coverage 略降（15→13）。原问题 Hybrid 是四组里文档检索最强的。

## 6. 额外调用、延迟与质量的权衡

四组调用成本：A/B = 24，C/D = 49（约 2 倍）。**多花的 25 次检索没有换来更好的覆盖，反而更差**。这直接回答了 Gate 3 的核心问题：在**这个** Planner + Dev 组合上，"分解检索更贵，且当前分解质量不足以覆盖收益"。

注意边界：这是"冻结 Planner v1 + Dev 24"的**一次受控观测**，不是全局规律——它只说明当前实现里分解的检索召回不如原问题单发，不说明"分解检索这个方向本身不可行"（更精确的分解、更长子问题、混合策略或许不同）。

## 7. 失败案例（哪些退化、哪些没救回来）

- **merge-drop 5 条义务**：candidate 覆盖 0.84 但 merge 后 0.73——round-robin 合并 + 5 条证据上限把一些本可覆盖的义务挤掉了。
- **multi_entity 最弱**：obligation 6/11（0.55）；troubleshooting 5/9（0.56）。这两个类型在 C/D 里覆盖最差。
- **fallback 3 条**（g3q021/g3q025/g3q034）：Planner 输出无效 → fallback 单发原问题 BM25；它们仍是 completed 但不含分解收益。
- **rescue 0 次**：没有任何子问题 BM25 空结果，Adaptive 的兜底一次也没用上。
- **refused 0**：所有子问题都至少命中一条，覆盖检查全部通过（哪怕覆盖不完全）。

## 8. 面试如何描述正结果或负结果

**负结果更要说清楚**：这不是"系统坏了"，而是受控实验如实暴露了"当前分解检索的召回弱于原问题单发"。

- 一句话版本："在冻结 Planner + Dev 上，分解检索（C/D）obligation 覆盖 0.73、调用 49 次，低于原问题 BM25（0.82、24 次）；Adaptive 因全部复杂题都被规划为 decomposed 而从未触发 hybrid，D=C。"
- 为什么可信：四组共享同一索引/快照/语料，只有执行方式不同；指标含原始分子分母；Artifact 防覆盖、无泄漏。
- 为什么不是结论："这是单次受控观测，样本 24 条；分解质量、子问题长度、合并上限都可能影响；真正的泛化要看 sealed Holdout。"
- 若将来是正结果，同样要报出代价（多几次调用、是否值得）。

## 9. 技术债与下一步

- **Adaptive 分支未被 Dev 覆盖**：需要"complex single"样本（Planner 把复杂题规划为 single 而不是 decomposed）才能真正测到 hybrid 分支。
- **merge-drop**：round-robin + 证据上限会丢弃已覆盖的义务；可评估更大 `max_evidence_items` 或更聪明的合并。
- **无答案评测**：本任务只测检索/覆盖；答案正确性（obligation 级 entailment）是 G3-E2E-07A 的事。
- **未跑 Holdout**：本对照是 Dev-only 证据，泛化结论需独立评测会话跑 sealed 数据。

---

## 边界声明

- 未读取/搜索 Gate 3 Holdout / sealed；示例与数字来自公开 Dev。
- 未调用真实 Planner / Generator；未运行 API Key。
- answer_generation=not_evaluated；不做答案正确性评测。
- 结果为单次受控观测，不宣称 Gate 3 完成或全局规律。
