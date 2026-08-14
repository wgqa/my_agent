# 75-Gate3子查询RRF合并实验

> G3-ADAPT-06C-MERGE：在 06B-R1 冻结结果之上，只改"多子问题证据合并策略"这一单变量（round-robin v1 → Reciprocal Rank Fusion v2），Dev-only 真实检索对照。
> 日期：2026-08-14
> run_id：`57811e77ecfa`；source_commit：`38866bc9b1870d79c38f4b3a66a77c8f126cc868`（Commit 1，tracked-clean 绑定）。
> 合并配置：`merge_policy=subquery_rrf_merge_v2`、`merge_rrf_k=60.0`；旧 `subquery_round_robin_v1` 保留为默认。
> 对照组：06B-R1 run `9afdb70e5c48`（source_commit 8c6d822，merge v1）。
> corpus：870e5864df67（37 files）；Dev：f2144030d754（24 Case）；Planner run：497808269bdd（冻结快照，C/D 共享）。
> 外部 Artifact：`benchmark_work/gate3/adaptive_dev_runs/57811e77ecfa/`（不入 Git）。

---

## 0. 结论先行（真实数字）

**v2（RRF merge）把 C/D 的 merge-drop 从 5 条义务降到 0，final obligation 覆盖从 32/44 提到 37/44，追回并超过了简单 A/B 的 36/44，检索调用数不变。**

| 指标（C/D） | v1（06B-R1） | v2（06C） | 变化 |
|---|---|---|---|
| candidate obligation 覆盖 | 37/44=0.841 | 37/44=0.841 | 不变（candidate 池未动） |
| **final obligation 覆盖** | **32/44=0.727** | **37/44=0.841** | **+5 条义务** |
| merge-drop 义务数 | 5 | **0** | -5 |
| full coverage | 13/20=0.65 | 16/20=0.80 | +3 |
| multi-obligation 完整 | 9/16=0.563 | 12/16=0.75 | +3 |
| Hit@5 | 0.90 | 0.95 | +0.05 |
| Recall@5 | 0.783 | 0.875 | +0.092 |
| MRR | 0.775 | 0.817 | +0.042 |
| nDCG@5 | 0.738 | 0.808 | +0.070 |
| 检索调用数 | 49 | 49 | 不变 |
| rescue used | 0 | 0 | 不变 |
| fallback | 3 | 3 | 不变 |
| refused | 0 | 0 | 不变 |

逐 case（C、D 相同）：**improved 3**（g3q008 covered 0→3、g3q015 1→2、g3q019 2→3，均从不完整变完整）、**regressed 0**、**unchanged 17**。没有任何一个 case 变差，只是候选到最终的"选人顺序"变了。

这达到并超过任务设定的"明显成功"门槛（merge-drop 显著下降 ✓、final obligation ≥ +2 ✓、调用不增 ✓、无核心指标恶化 ✓），并且 C/D 的 37/44 已经**超过** A/B 的 36/44——rank-based 合并不仅止损，还追回了简单检索的覆盖水平。

## 1. 为什么 candidate coverage 和 final coverage 不一样

候选（candidate）是所有子问题检索返回的**去重文档集**；最终证据（final evidence）是 merge 之后**实际放进 EvidenceBundle 的前 5 条**。

- candidate 覆盖 37/44：只要某条义务的文件出现在**任何一个子问题的返回里**就算候选命中。
- final 覆盖 32/44：只有最终这 5 个位置里包含那个文件才算。

06B-R1 里两者差 5 条义务，就是 **merge-drop**：候选里明明有能覆盖义务的文档，却被合并/截断挤掉了。这就是信息损失的根源——不是检索没召回，是"从召回集到最终证据"这一步丢了。

## 2. Round-robin（v1）原理，以及它为什么丢候选

`subquery_round_robin_v1`：每轮从每个子问题**各取一个尚未入选的候选**，轮流贡献。

```
sq1: [A, B, C]   sq2: [D, E]
round 1: 取 A(sq1), D(sq2) → [A, D]
round 2: 取 B(sq1), E(sq2) → [A, D, B, E]
round 3: 取 C(sq1)          → [A, D, B, E, C]  （满了，停）
```

问题：最终 5 个位置被 **子问题顺序 × 每轮取一个 × Evidence=5 截断** 三重因素锁死。它不比较"这个文档在多个子问题里是否都靠前"，只按"轮到哪个子问题"排。于是：一个只在 sq2 靠前、但在 sq1 也出现的文档，可能因为 sq1 前面已经占满而进不了最终 5 条；而 sq1 里一个仅排第 3、覆盖不了义务的文档却占了位置。06B-R1 的 5 条 merge-drop 就来自这里。

## 3. Reciprocal Rank Fusion（v2）原理

RRF 是**纯 rank 的融合**：对同一份候选文档 d，跨所有子问题累加它的倒数排名：

```
merge_score(d) = Σ_i  1 / (merge_rrf_k + rank_i(d))
```

- `rank_i(d)`：d 在子问题 i 的检索结果里的名次，从 1 开始；
- 只在 d **真正出现**的子问题累加；没出现的子问题贡献严格为 0；
- `merge_rrf_k = 60.0`（平滑项，防止排名 1 的文档分数过高，并压低噪声）。

排序契约：`merge_score DESC → best_rank ASC → source_name ASC`，然后**去重到文档级**、截断到 `max_evidence_items=5`、重编号 citation。`best_rank(d) = min_i rank_i(d)` 作为第二个键；最后以文档源名升序做确定性 tie-break（runtime 层不持有 evaluation 的 canonical 相对路径，源名升序即其确定性的 canonical 身份键）。

例如 d 在 sq1 第 1、sq2 第 3：`merge_score = 1/61 + 1/63`。它在"多个子问题里都靠前"这件事被显式奖励——这正是 round-robin 没有的。

## 4. 为什么不比较原始 BM25/Dense 分数

BM25 分数、Dense 距离、Hybrid 的 RRF score 都是**各自 channel 内部的**，跨子问题不可比：同一个词在不同子问题下打分分布完全不同。直接跨子问题比原始分数等于拿尺子在不同单位之间比大小。RRF 只比"名次"，而名次（rank）在任意 channel 里都是 1、2、3… 的可比单位，所以它能跨 ranked lists 融合而不引入 channel 偏差。

06C 的实现里 merge 函数完全不读 `doc.score`，测试也专门验证"分数改了、顺序不变"。

## 5. RRF 为什么能跨 ranked lists

rank 是**位置语义**：每个子问题的 top-1 都是"该子问题下最相关"。`1/(60+rank)` 把"第几名"换算成可累加的贡献分，于是不同子问题的同位置文档可以相加。k 越大，排名间的分数差越小、融合越平滑（等价于把"跨 list 比较"变得温和）；k 越小，top 名次的权重差越陡。60 是实践常用的平滑值。

## 6. deterministic tie-break 为什么重要

merge 之后还有 MRR / nDCG 这类对**顺序敏感**的指标。如果并列时不给定序规则，不同机器/不同次运行会给出不同顺序，实验不可复现，指标噪声直接污染单变量结论。所以 v2 把三个键排死：分数降序 → 最好名次升序 → 源名升序。测试覆盖"best_rank tie 与 source tie 都确定"。这也是本项目一贯的"测试假阳性要防、可复现性要命"纪律。

## 7. 为什么这是单变量实验

对冻结 run `9afdb70e5c48` 逐 case 验证：

- **A/B**：case 集、retrieved 结果、metrics、retrieval call 全部**逐字节一致**；
- **C/D merge 前**：plan_id、route、retrieval_call_count、candidate_canonical_paths、fallback、retriever strategy **全部一致**；
- candidate 池 0 处差异（不满足就立即停止，实验作废）。

允许变化的只有：最终 evidence 顺序/集合，以及由此产生的最终指标。整条链路里唯一的输入差异是 `merge_policy`（v1→v2），所以任何指标变化都能归因到 merge，而不是 Retriever / Planner / 候选。

## 8. 真实 v1/v2 指标（原始分子分母）

见 §0 表。补充：candidate 37/44 保持不变证明了"不是候选变多，是选人选对了"；final 32→37 且 full 13→16、multi 9→12，全部来自三个 case（g3q008/g3q015/g3q019）从不完整变完整，零回归。

## 9. 如果 v2 失败，为什么失败仍有价值

负结果同样是一等公民：它说明"在 5 位置预算下，任何合并策略都无法超过候选覆盖的上限（37/44）"——即瓶颈在**检索召回**而非合并选择。那下一步该投的是 query rewrite / 更长子问题 / 更多候选，而不是 merge。这跟 06B-R1 的负结果是一个逻辑：受控实验的最大价值是**把"哪里不行"钉死**，让团队不在错的方向上继续调。本实验结果是正面的，但这条"失败也有信息量"的框架不变。

## 10. 面试追问（如何回答）

- **为什么不用 Cross-Encoder？** Cross-Encoder 是**重排**（rerank）：给定候选集，用模型逐对算相关性。它贵（每个候选要一次前向）、要在线调用，且本任务要的是**在固定候选、固定调用预算下的确定性选择**，不是模型打分。RRF 零成本、可复现、不进模型；将来要上 Cross-Encoder 也是在 RRF 选出 top-5 之后对候选做重排，两者不冲突。
- **为什么不直接把 Evidence 扩成 10？** 那会改 `max_evidence_items`（Evidence Budget），破坏单变量——而且扩预算只是"多给几个位置"，不解决"选哪个文档"的问题，还会放大 prompt 长度与生成成本。实验要隔离变量：先证明"同预算下选人更准"。
- **RRF 的 k 有什么作用？** k 是平滑项：k 越大，不同排名间的贡献差越平（跨 list 融合越温和）；k 越小，top 名次权重差越陡。60 是常用默认值。注意：本实验 k 固定 60，改 k 就是换第二个变量，会退出单变量框架。
- **为什么不能在 Dev 上不停调 k？** 反复在同一个 Dev 上试 10/20/30/50/100 挑最好，等于把 Dev 当训练集（过拟合到 24 个 case），测出来的提升不可泛化，也从"受控实验"变成"调榜"。要调 k，只能去独立评测会话、在 sealed Holdout 上做一次，且预设假设。
- **如何证明收益来自 merge 而不是 Retriever？** 三条证据链：① 检索调用数与策略分布不变；② candidate 池逐 case 字节一致（Retriever 输出没变）；③ A/B 两组指标逐字节一致（Retriever 行为整体没变）。唯一变化的输入是 merge_policy，所以收益只能来自 merge。

## 11. 技术债与下一步

- **v2 只改了 merge 选择，没改检索**：37/44 已是当前候选上限，想再往上要动检索/Planner（那是另一组受控实验）。
- **candidate 覆盖仍只有 37/44**：7 条义务的文档根本没被任何子问题召回，这是检索层问题，不是 merge 能解决的。
- **答案评测仍未做**：本实验只测检索/覆盖；答案正确性（obligation 级 entailment）留给 G3-E2E-07A。

---

## 边界声明

- 未读取/搜索 Gate 3 Holdout / sealed；只用了公开 Dev、冻结 corpus、冻结 planner snapshot 497808269bdd。
- 未调用真实 Planner / Generator；未运行 API Key。
- 只改了 merge 选择策略这一个变量；未改 QueryPlan/query rewrite/BM25/Hybrid/Adaptive Router/rescue condition/verifier/max retrieval calls/candidate_k/top_k/max_evidence_items。
- 结果来自真实新 run `57811e77ecfa`；旧 run `9afdb70e5c48` 未删除未覆盖。
- Dev-only 受控观测，不宣称全局规律；泛化结论需独立评测会话跑 sealed 数据。
