# Dense-only / BM25-only Formal Strategy Confirmation（G2-ABL-16）

> 2026-08-08
> 本报告用两个**独立正式实验**确认 offline / counterfactual channel
> ablation（G2-ABL-15）的结论是否可复现。

## 1. offline ablation 为什么不等于 formal experiment

G2-ABL-15 的 Dense/BM25 指标来自 canonical Hybrid 内部已保存的
channel candidates，属于 post-hoc 推导：

- 没有自己的 `index_manifest` / `retrieval_results` / `retrieval_metrics`
  / `result`；
- 没有独立 `experiment_id`；
- 排序逻辑在分析脚本里，而不是正式 Retriever 运行时。

formal experiment 则通过 `ExperimentRunner.run_experiment()` 完整执行
prepare → index → retrieval → metrics → finalize，每个策略都有独立
实验身份与正式 Artifact。

## 2. 为什么还需要两个独立 experiment identity

因为 offline 结论不能冒充正式实验事实：

```text
同一个 Corpus + 同一个 Gold + 不同 retriever_strategy
→ 必须分别拥有 experiment_id / retrieval_run_id / metrics_run_id / result_id
```

否则"某策略表现如何"无法被独立审计和复现。

## 3. 控制变量

除 `retriever_strategy` 外全部与 canonical Hybrid 一致：

```text
corpus_id         = 870e5864df67
evaluation_set_id = 18c1c0470652
embedding         = bge / BAAI/bge-small-zh-v1.5
chunk_strategy    = recursive（512/64）
top_k             = 5
dense_candidate_k = 30（统一配置字段）
sparse_candidate_k= 30（统一配置字段）
rrf_k             = 60（统一配置字段）
rrf_tie_breaker   = chunk_id_asc（统一配置字段）
```

说明：`dense_candidate_k` / `sparse_candidate_k` / `rrf_k` /
`rrf_tie_breaker` 存在于统一 ExperimentConfig，但不代表 simple/bm25
策略实际消费它们（simple 只用 Dense Top-5，bm25 只用 BM25 Top-5）。

## 4. Dense / BM25 / Hybrid 三个正式结果

```text
               Hit@5    Recall@5   MRR       nDCG@5
Dense(simple)  0.88     0.863333   0.748333  0.762381
BM25(bm25)     0.98     0.953333   0.787333  0.820643
Hybrid         0.92     0.893333   0.786667  0.799360
```

正式身份：

| 策略 | experiment_id | retrieval_run_id | metrics_run_id | result_id |
|------|---------------|------------------|----------------|-----------|
| Dense | dc220d794578 | bf1c0d99a952 | a5ddaecf5c2d | c2d4ec845d9e |
| BM25 | dbc497c796d5 | 4af4d4e8a052 | 608187a6f3ad | acd92171966d |
| Hybrid | 3c613202e1ed | fc228af22f55 | 966ed53156e4 | e27141a2b63e |

均确认：corpus_id=870e5864df67、evaluation_set_id=18c1c0470652、
file_count=37、total_chunks=215、case_count=50、top_k=5。

## 5. offline vs formal parity（宏指标）

| 指标 | Dense formal - offline | BM25 formal - offline |
|------|------------------------|------------------------|
| Hit@5 | 0.0 | 0.0 |
| Recall@5 | 0.0 | 0.0 |
| MRR | 0.0 | 0.0 |
| nDCG@5 | 0.0 | 0.0 |

绝对 delta 全部为 0。

## 6. Case-level parity

定义 exact match = Top-5 chunks 对应的 document ranking 与顺序完全一致。

```text
Dense：50 / 50 exact match（无任何 Case 差异）
BM25 ：50 / 50 exact match（无任何 Case 差异）
```

额外记录 chunk 粒度（Top-5 chunk_id 顺序）：

```text
Dense：50 / 50 exact match
BM25 ：50 / 50 exact match
```

两种粒度均为 50/50，未发现 reproducibility discrepancy。

## 7. 当前 Benchmark 的真实排序

按 Hit@5 / Recall@5 / nDCG@5：

```text
BM25-only > Hybrid > Dense-only
```

按 MRR：

```text
BM25-only ≈ Hybrid > Dense-only
```

## 8. 是否正式确认策略排序

**是**，范围限定为：

```text
当前 50 Case、top-5-chunk 语义、技术八股语料
```

在此范围内正式确认：

```text
BM25-only 观测指标最高
Hybrid 次之（相对 BM25 是净损失，相对 Dense 是净收益）
Dense-only 最低
```

这不是普遍规律，不推广到其他语料/Query 分布。

## 9. 结论适用范围

- 适用：本 Benchmark 的正式 Baseline 对比、后续消融设计的参照；
- 不适用：其他语料、其他 top_k、其他 Embedding、其他语言；
- 不能因此删除 Hybrid：正式结果确认 Hybrid 相对 Dense 有净价值，
  相对 BM25 是净损失，选择取决于线上需求。

## 10. 下一实验假设

1. 为什么 BM25-only 在当前 50 Case Benchmark 上的观测指标明显高于
   Dense-only？（词法命中在当前语料上是否比语义近邻更占优？）
2. Reranker / candidate_k 调整能否减少 Hybrid 相对 BM25 的 3 个
   fusion regression——必须作为正式实验验证。
3. 若引入 document-level 聚合假设，需要 chunk-level Gold Label。

## 代码与身份边界

本项目原本没有 BM25-only 正式策略，本任务最小新增：

- `core/retriever/bm25_only.py`：`BM25OnlyRetriever`（复用 BM25Index，
  不参与 Dense/RRF）；
- 合法策略集合增加 `bm25`（Config 与 ExperimentConfig）；
- CLI `--retriever-strategy`（simple/hybrid/bm25）。

这是正式确认所需的最小实现，不涉及任何参数优化。

## 审计说明（G2-ABL-16-R1）

- ABL-16 原始 BM25 Manifest（`experiments/dbc497c796d5/`）的
  `sparse_index_count` 为 null，属于历史执行事实，**未修改**；
- 性能结果由于 formal/offline 在 document ranking 与 chunk_id 两个
  粒度均为 50/50 exact match，得到独立行为验证；
- R1 已修复未来 BM25 formal run 的 sparse integrity contract：
  `hybrid / bm25 → sparse_index_count == vector_store_count`，
  `simple → sparse_index_count = null`；
- 本报告所有指标保持不变，未重跑、未覆盖任何历史 Artifact。
