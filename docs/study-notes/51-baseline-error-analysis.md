# 第一次真实 Baseline Retrieval Error Analysis（G2-ANALYSIS-12）

> 2026-08-08 — 文档任务（无代码/测试变更）
> 第一次真实 Baseline 的价值不只是数字，而是把“哪些失败是事实、
> 哪些失败需要新证据”划清楚；分析报告本身也要遵守证据边界，不能
> 用猜测填满表格。

## 分析对象

冻结的 embedding-bound Baseline：

```text
experiment_id = 874b61d0b5d1
result_id     = 325d94294803
corpus_id     = 870e5864df67
evaluation_set_id = 18c1c0470652
```

只读四个正式 Artifact（index_manifest / retrieval_results /
retrieval_metrics / result）+ Benchmark Corpus + Gold；不重新运行实验、
不调参、不修改任何数据。

## 证据边界（最重要的纪律）

当前 `retrieval_results.json` 只保存最终 Top-5 Hit 的
`dense_rank` / `sparse_rank`，**没有保存完整 top-30 channel candidate
snapshot**。

因此：

```text
如果 Gold 没有进入最终 Top-5，
就不能声称"Gold 在 Dense 第 X"或"BM25 根本没召回 Gold"。
```

报告统一写法：

> 现有 Artifact 无法判断，需要后续 channel-level diagnostic / ablation。

这条边界同时给出了下一步评测基础设施的缺口：正式检索快照应当
增加 channel-level 候选保存能力（dense top-30 / sparse top-30），
否则错误分析只能停在"最终排名"层面。

## 分析方法

1. 从 `retrieval_metrics.json` 提取 50 Case 指标分布与最差 10 Case；
2. 从 `retrieval_results.json` 提取重点 Case 的 Gold、Top-5、
   逐 Hit 的 dense_rank / sparse_rank / rrf_score；
3. 只读 Corpus 文件标题与首段，建立"错误召回文档 vs Gold 主题"
   的事实关系；
4. 只做事实分类，证据不足明确标注。

## 失败类型（事实层面）

| case_id | 分类 |
|---------|------|
| q013 / q039 / q047 | semantic-neighbor confusion（最终 Top-5 被语义邻近文档占据） |
| q019 | semantic-neighbor confusion（同系列同标题文档抢占）；possible chunk-boundary（无法验证） |
| q031 / q034 | multi-document incomplete recall（1/2 Gold 未进 Top-5）+ semantic-neighbor confusion |
| q036 | multi-document incomplete recall（2/3 Gold 命中，Tool 层 Gold 缺失）+ semantic-neighbor confusion |

4 个 Hit@5=0 Case 的通道候选状态全部未知，统一按证据不足处理。

## 50 Case 指标分布要点

- Hit@5：1.0 × 46，0.0 × 4；
- Recall@5：1.0 × 43，[0.5, 1.0) × 3，0.0 × 4；
- MRR=0 × 4；first_relevant_rank：1 → 34，2 → 8，3 → 4，None → 4；
- nDCG@5：1.0 × 30，[0.5, 1.0) × 16，0.0 × 4。

## 假设与证据等级

```text
H1 失败主要来自 Dense/BM25 都偏向语义邻居
   -> plausible / currently unverified（通道层）
H2 正确文档进入某一通道候选但 RRF 排名丢失
   -> currently unverified
H3 Chunk 边界让 Gold 文档中的目标证据表达被削弱
   -> plausible / currently unverified
H4 Multi-file Query 单次检索只覆盖部分子问题
   -> supported（q031/q034/q036 事实支撑）
```

假设只用于选择消融方向，不执行实验。

## 教训

1. **证据边界要先于结论**：没有 channel 快照时，任何关于
   "Dense 第几 / BM25 没召回" 的结论都是伪造证据；宁可写
   "无法判断"。
2. **失败分类要绑定证据等级**：semantic-neighbor confusion 是
   最终排名的可观察事实；通道偏置、RRF 丢失、Chunk 边界都是
   待验证假设，不能混为一谈。
3. **多文件查询是独立的失败模式**：q031/q034/q036 全部命中一个
   Gold 却缺失另一个，且缺失文件与查询子问题直接对应，这为
   "单次检索覆盖不足"提供了可复现的事实样本。
4. **报告揭示基础设施缺口**：本次分析暴露的 channel-level 快照缺失，
   本身就是下一轮评测基础设施改进的输入。
