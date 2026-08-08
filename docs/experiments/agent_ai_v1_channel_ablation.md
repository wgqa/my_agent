# Dense vs BM25 vs Hybrid Channel Ablation（G2-ABL-15）

> 2026-08-08
> 本报告是 **offline / counterfactual channel ablation**：指标来自
> canonical Hybrid Baseline 内部已经执行并保存的 channel candidate
> snapshot（diagnostic_id=dfb2316d0163，retrieval_run_id=fc228af22f55），
> 不是三个独立正式 ExperimentResult。

## 1. 为什么先做 Dense / BM25 / Hybrid

G2-ANALYSIS-14 发现 q039 存在"两个通道都找到同一 Gold 文档、但落在
不同 Chunk、Hybrid Final 缺失"的模式。要判断这是否是系统性损失，
必须先知道：单通道各自在文档级表现如何，Hybrid 相对它们净赚多少、
净亏多少。本任务只回答事实，不调任何参数。

## 2. 为什么可以从现有 diagnostic 做离线消融

canonical `retrieval_diagnostics.json` 已保存每个 Case 的：

```text
dense_candidates（Dense Top-30）
sparse_candidates（BM25 Top-30）
final_hits（Hybrid RRF Final Top-5）
relevant_files（Gold）
```

因此 Dense-only / BM25-only 的文档排名可以直接从候选快照离线推导：
Query、Chunk、索引、Embedding 完全一致，不存在二次运行随机性。
它**不是** `retriever_strategy="simple"/"bm25"` 的独立正式实验。

## 3. Top-5 Chunk → Document ranking 规则

与正式系统完全一致：

```text
取该通道前 5 个 Chunk（按 channel rank）
→ 按第一次出现顺序对 relative_path 去重
→ 得到文档 ranking
```

禁止"先按文档去重、再取前 5 个文档"——那会改变
`top_k = 5 chunks → retrieved_files dedup` 的正式语义。
Hybrid 直接用 canonical `final_hits` 前 5 个 Chunk 再去重，不重算 RRF。

## 4. 三组宏指标（50 Case，真实结果）

| 策略 | Hit@5 | Recall@5 | MRR | nDCG@5 |
|------|-------|----------|-----|--------|
| Dense-only | 0.88 | 0.863333 | 0.748333 | 0.762381 |
| BM25-only | **0.98** | **0.953333** | **0.787333** | **0.820643** |
| Hybrid | 0.92 | 0.893333 | 0.786667 | 0.799360 |

注意：**本 Benchmark 上 BM25-only 四项宏指标全部最高**；Hybrid 介于
两者之间，不是总体最优。不预设 Hybrid 最好。

## 5. Case outcome 分布

```text
all_success        = 42
hybrid_rescue      = 4（全部 rescues_dense；rescues_sparse=0，rescues_both=0）
fusion_regression  = 4（regression_dense=1，regression_sparse=2，regression_both=1）
all_fail           = 0
recall_regression  = 2（q031、q034：Hybrid Recall 低于 Dense-only）
```

## 6. fusion rescue 数

Hybrid 比 Dense 多命中 4 个 Case（Dense 失败而 Hybrid 成功）；比
BM25 多命中 0 个 Case。

## 7. fusion regression 数

Hybrid 比 Dense 少命中 2 个 Case；比 BM25 少命中 3 个 Case。
另有 2 个 multi-file Case（q031、q034）虽然 Hit 都成功，但 Hybrid
Recall@5 从 Dense-only 的 1.0 降到 0.5。

## 8. multi-file Recall 变化

- q031：Dense Recall=1.0，Sparse=0.5，Hybrid=0.5 → recall_regression
- q034：Dense Recall=1.0，Sparse=1.0，Hybrid=0.5 → recall_regression
- q036：三者 Recall 均为 0.666667，无 regression

Hybrid 在 multi-file Case 上更容易丢失"第二个 Gold 文档"，与
G2-ANALYSIS-14 的 H4/H5 方向一致。

## 9. 7 个重点 Case

| case | Dense | BM25 | Hybrid | 结论 |
|------|-------|------|--------|------|
| q013 | Hit ✓（first rank 3，MRR 0.333） | ✗ | ✗ | fusion_regression（dense） |
| q019 | ✗ | Hit ✓（first rank 2，MRR 0.5） | ✗ | fusion_regression（sparse） |
| q039 | Hit ✓（recall 1.0，MRR 1.0） | Hit ✓（recall 1.0，MRR 0.5） | ✗ | fusion_regression（both） |
| q047 | ✗ | Hit ✓（recall 1.0，MRR 1.0） | ✗ | fusion_regression（sparse） |
| q031 | Hit ✓（recall 1.0） | Hit ✓（recall 0.5） | Hit ✓（recall 0.5） | all_success + recall_regression |
| q034 | Hit ✓（recall 1.0） | Hit ✓（recall 1.0） | Hit ✓（recall 0.5） | all_success + recall_regression |
| q036 | Hit ✓（recall 2/3） | Hit ✓（recall 2/3） | Hit ✓（recall 2/3） | all_success |

### 特别确认

- **q019**：BM25-only 确实命中（Gold 在 Sparse 候选 rank 2，按
  Sparse 前 5 Chunk 语义进入文档 rank 2，MRR=0.5）；Hybrid 却把它
  融合丢失。
- **q039**：在"各自 Top-5 Chunk 去重后文档 ranking"语义下，Dense-only
  和 BM25-only **都成功召回** Gold 文档（Dense MRR=1.0，Sparse
  MRR=0.5），Hybrid Final 却完全缺失——这比"只进 Top-30 候选"更强，
  证明两个单通道的文档级正确结果被 chunk-level RRF 融合丢失。

## 10. 对 H1-H5 的影响

- **H1（两路通道都偏向语义邻居）**：进一步不被支持作为主因；
  BM25-only 反而在 Hit/Recall 上最强，Dense-only 最弱。
- **H2（正确文档进入候选但 RRF 后掉出 Top-5）**：**证据大幅增强**。
  4 个 fusion_regression Case（q013/q019/q039/q047）+ 2 个
  recall_regression Case，全部是"单通道文档级成功、Hybrid 丢失"。
- **H3（Chunk 边界削弱证据）**：保持 plausible / currently
  unverified；本任务无法区分"碎片化"与"Chunk 内证据不足"。
- **H4（multi-file 单次检索覆盖不足）**：supported；q031/q034 的
  Hybrid Recall 明显低于 Dense-only。
- **H5（Chunk-level RRF 无法聚合跨通道跨 Chunk 信号）**：**证据升级为
  supported 的候选解释之一**——q039 是两个单通道文档级都成功而
  Hybrid 失败的典型；但本任务仍不能宣称 document-level fusion
  一定更好。

## 11. 下一组实验应该回答什么

1. 为什么 BM25-only 在当前 50 Case Benchmark 上的观测指标明显高于
   Dense-only？
   （词法命中在当前语料上是否比语义近邻更占优？）
2. 在 Hybrid 中，Reranker（候选 20 → 最终 5）或 candidate_k 调整
   能否减少 fusion_regression？——必须作为正式实验验证，不能凭
   本离线结果下结论。
3. 若引入 document-level 聚合假设，需要 chunk-level Gold Label
   才能区分"信号碎片化"与"证据不存在"。

## 当前 Hybrid 的净价值（必须如实回答）

```text
Hybrid 相比 Dense：
修复 4 cases（Dense 失败而 Hybrid 成功）
损失 2 cases（Dense 成功而 Hybrid 失败）
宏指标：Hit 0.88 → 0.92；Recall 0.8633 → 0.8933；
        MRR 0.7483 → 0.7867；nDCG 0.7624 → 0.7994

Hybrid 相比 BM25：
修复 0 cases
损失 3 cases（BM25 成功而 Hybrid 失败）
宏指标：Hit 0.98 → 0.92；Recall 0.9533 → 0.8933；
        MRR 0.7873 → 0.7867；nDCG 0.8206 → 0.7994
```

结论：在本 Benchmark 的 top-5-chunk 语义下，**Hybrid 相对 Dense 有
正净价值，相对 BM25 是净损失**。不能因为"Hybrid 高于 Dense"就宣布
RRF 完成；也不能因为本离线结果就删除 Hybrid。

## 数据来源与边界

- `experiments/3c613202e1ed/agent-ai-v1-recursive-hybrid-baseline-001-diagnostics/retrieval_diagnostics.json`
- 输出 Artifact：`docs/experiments/agent_ai_v1_channel_ablation.json`
- 身份边界：offline / counterfactual channel ablation，不是三个
  独立正式 ExperimentResult；如需正式身份需另行运行确认实验。
