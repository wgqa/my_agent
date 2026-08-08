# BGE-Aligned Chunk Budget Formal Retrieval Ablation（G2-ABL-21）

> 正式 intervention 实验：Recursive Chunk Budget 从
> `cl100k_content_v1` 切换为 `embedding_runtime_model_input_v1`，
> 将实际会截断的 chunk（57/215 → 0）后，Dense / BM25 / Hybrid
> 的正式 Retrieval 结果变化。
>
> 本实验验证的是 BGE-aligned chunk-budget intervention 的整体效果，
> 不能严格隔离"只因为 truncation 消失"这一单一因果机制。

## 1. 研究问题

```text
当 Recursive Chunk Budget 从 cl100k_content_v1
改为 embedding_runtime_model_input_v1，
并将当前 BGE runtime 中实际会截断的 Chunk：57 / 215 → 0，
Dense / BM25 / Hybrid 的正式 Retrieval 结果如何变化？
```

## 2. 实验配置（冻结）

```text
corpus_id         = 870e5864df67
evaluation_set_id = 18c1c0470652
file_count        = 37
case_count        = 50
top_k             = 5

embedding_provider = bge
embedding_model    = BAAI/bge-small-zh-v1.5

chunk_strategy     = recursive
chunk_budget_policy= embedding_runtime_model_input_v1
chunk_size         = 512（v1 中含义为 model-input budget）
chunk_overlap      = 64（content-token overlap）

dense_candidate_k  = 30
sparse_candidate_k = 30
rrf_k              = 60
rrf_tie_breaker    = chunk_id_asc
```

Runtime 全部由 resolver 正式解析，未手填：

```text
effective_embedding_max_seq_length = 512
special_token_overhead             = 2
tokenizer_contract_probe_version   = "v1"
tokenizer_contract_fingerprint     = e8e75c158a1505f2
runtime_tokenizer_class            = BertTokenizer
```

三套实验解析出的 runtime contract 完全一致。

## 3. 三套正式实验身份

```text
A. Recursive + Dense（simple）
   experiment_id   = 04fc6d2111a6
   retrieval_run_id= 0c71b0f29491
   metrics_run_id  = f558c0ae747d
   result_id       = 805658b71e76

B. Recursive + BM25（bm25）
   experiment_id   = b35b1102197e
   retrieval_run_id= 40d2e21e3bc2
   metrics_run_id  = e31e22858dde
   result_id       = 812d4d4e2bd2

C. Recursive + Hybrid（hybrid）
   experiment_id   = e680cdf278b2
   retrieval_run_id= 6d295e9ed5f8
   metrics_run_id  = 68b33512c51b
   result_id       = 26327c177e37
```

## 4. Manifest v2 与 Chunking Observed Facts

三套 Manifest 均满足：

```text
schema_version = 2
file_count     = 37
total_chunks   = 215 == vector_store_count = 215

actual_content_token_max     = 510
actual_model_input_token_max = 512
actual_would_truncate_count  = 0

corpus_scoped_tokenizer_behavior_fingerprint
  = d39634c168e74677（三套一致）
```

Sparse integrity：

```text
Dense:  sparse_index_count = None
BM25:   sparse_index_count = 215 == vector = 215 == total = 215
Hybrid: sparse_index_count = 215 == vector = 215 == total = 215
```

干预成功硬条件满足：`actual_would_truncate_count == 0`、
`actual_model_input_token_max == 512 <= 512`。

历史 Recursive cl100k 的 total_chunks 也是 215。**相同 chunk 数量
≠ 相同 chunk boundaries**：逐 Case 文档 ranking 大量变化（见第 7 节），
不能用相同总数推导 Chunk 没有变化。

## 5. 正式指标矩阵（aligned − historical）

```text
                     cl100k      aligned       delta

Dense Hit@5          0.88        0.84          -0.04
Dense Recall@5       0.863333    0.840000      -0.023333
Dense MRR            0.748333    0.669667      -0.078667
Dense nDCG@5         0.762381    0.707847      -0.054534

BM25 Hit@5           0.98        0.98           0.00
BM25 Recall@5        0.953333    0.943333      -0.010000
BM25 MRR             0.787333    0.785000      -0.002333
BM25 nDCG@5          0.820643    0.806386      -0.014258

Hybrid Hit@5         0.92        0.96          +0.04
Hybrid Recall@5      0.893333    0.933333      +0.04
Hybrid MRR           0.786667    0.763333      -0.023333
Hybrid nDCG@5        0.799360    0.795896      -0.003464
```

均为当前 50 Case Benchmark 上的 observed result，未执行统计显著性
检验，不使用"显著"类表述。

## 6. Case-Level 对照（aligned vs historical，50 Case）

```text
                 exact doc ranking  changed  hit rescue  hit loss
Dense            3 / 50             47       1（q029）   3（q023/q036/q045）
BM25             14 / 50            36       0           0
Hybrid           13 / 50            37       2（q039/q047） 0

                 recall improved  recall worsened  unchanged
Dense            2                 3                45
BM25             0                 1（q033）         49
Hybrid           2                 0                48
```

方向性说明：

- Dense 是主要受损路径：Hit −4（3 loss / 1 rescue），MRR/nDCG 下降；
- BM25 aggregate metrics 较稳定：Hit 0 rescue / 0 loss，仅 q033 的
  multi-file Recall 从 1.0 降到 0.5；但其 document ranking 36/50
  发生变化（详见第 9 节）；
- Hybrid 是主要受益路径：Hit +4（q039/q047 rescue，0 loss），
  Recall +0.04，但 MRR/nDCG 微降（排名位置变化）。

## 7. Multi-file Recall

```text
q031: dense 1.000->1.000 | bm25 0.500->0.500 | hybrid 0.500->0.500
q032: dense 1.000->1.000 | bm25 1.000->1.000 | hybrid 1.000->1.000
q033: dense 1.000->1.000 | bm25 1.000->0.500 | hybrid 1.000->1.000  ← BM25 regression
q034: dense 1.000->1.000 | bm25 1.000->1.000 | hybrid 0.500->0.500
q035: dense 0.500->1.000 | bm25 1.000->1.000 | hybrid 1.000->1.000  ← Dense improved
q036: dense 0.667->0.000 | bm25 0.667->0.667 | hybrid 0.667->0.667  ← Dense regression
q038: dense 1.000->1.000 | bm25 0.500->0.500 | hybrid 1.000->1.000
```

## 8. 重点失败 Case

```text
q013（llm/预训练.md）
  Dense:  Hit 1->1（first 3->4）；BM25: 0->0；Hybrid: 0->0
  变化：无 Hit 变化；Dense Gold 仍在 Top-5 但排名后移。

q019（llm/Transformer架构-03）
  Dense: 0->0；BM25: 1->1（first 2->3）；Hybrid: 0->0
  变化：无 Hit 变化。

q039（rag/检索与生成.md）
  Dense: 1->1（first 1->1）；BM25: 1->1（first 2->2）
  Hybrid: 0->1（first absent->3）→  RESCUE

q047（llm/Transformer架构-04）
  Dense: 0->0；BM25: 1->1（first 1->1）
  Hybrid: 0->1（first absent->2）→  RESCUE

q031（rag/文档处理.md, rag/检索与生成.md）
  Dense: 1.0->1.0；BM25: 0.5->0.5；Hybrid: 0.5->0.5
  变化：无。

q034（rag/高级RAG.md, rag/检索与生成.md）
  Dense: 1.0->1.0（first 1->2）；BM25: 1.0->1.0；Hybrid: 0.5->0.5
  变化：无 Recall 变化。

q036（提示工程高级技巧.md, rag/文档处理.md, Function-Calling原理.md）
  Dense: Hit 1->0，Recall 0.667->0.000 →  LOSS
  BM25: 0.667->0.667；Hybrid: 0.667->0.667（first 1->2）
```

注意：q036 的 Gold 文件中存在截断风险 chunk（DIAG-18），但 aligned
后该 Case 的 Dense 反而失败，不能据此宣称"截断导致失败"或"消除截断
就修复失败"；chunk boundary 同时改变是更可能的解释，需要
Case-level 与 channel-level 证据。

### q039 / q047 的 Fusion 解释仍开放

```text
q039：Dense Gold doc rank 1 -> 1
      BM25 Gold doc rank 2 -> 2
      Hybrid: absent -> rank 3

q047：Dense: miss -> miss
      BM25 Gold doc rank 1 -> 1
      Hybrid: absent -> rank 2
```

因此不能把两个 Hybrid rescue 简化为"Dense aligned 后变好，所以
Hybrid 被 rescue"：q039 的 Dense/BM25 单通道本来就命中，q047 的
Dense 仍 miss 而 BM25 一直命中，document-level 证据不支持该故事。
更合理的开放假设包括 chunk-level channel ranks、chunk identity、
cross-channel overlap、RRF fusion geometry——但本任务不跑新的
channel diagnostic，**mechanism currently unresolved**，Gate 2
不为此继续深挖。

## 9. BM25 Control 的解释

```text
BM25: Hit 0.98 -> 0.98（0 rescue / 0 loss）
      Recall -0.01（仅 q033 multi-file）
      MRR -0.0023 / nDCG -0.0143（排名微调）

同时：
BM25 exact document ranking：
  14 / 50 相同
  36 / 50 发生变化
```

因此不能写"BM25 基本不变 → chunk-boundary / lexical mechanism 较弱
→ 支持 embedding-input alignment 是重要机制"。这个推断过强。

准确表述：

```text
BM25 的 Gold-level aggregate metrics 较稳定，
但其 document ranking 仍有 36/50 Case 发生变化。

因此 chunk-budget intervention 对 BM25 retrieval behavior
同样产生了广泛影响，只是这些 ranking 变化多数没有跨越当前
Gold metric 的命中/Recall 边界。
```

这不能单独把 Dense/Hybrid 变化归因到 embedding-input alignment；
general chunk-boundary / lexical pathway 是否变化仍然开放。

## 10. 当前能够 / 不能支持的结论

能支持：

```text
1. 干预成功：would-truncate 57/215 -> 0（正式 Manifest observed facts）；
2. 三套 aligned 实验 chunking observed facts 完全一致（215 chunks、
   content max 510、model-input max 512、corpus-scoped fp 相同）；
3. aligned intervention 对三种 strategy 的 retrieval behavior 都产生
   了实质影响（文档 ranking 变化 Dense 47/50、BM25 36/50、
   Hybrid 37/50）；
4. Gold-level performance impact 在当前 Benchmark 上具有
   strategy-dependent pattern：
   Dense 整体变差；BM25 aggregate metrics 较稳定；Hybrid Hit/Recall
   提升、MRR/nDCG 略降；
5. 因为 BM25 ranking 本身 36/50 发生变化，不能说 general
   chunk-boundary / lexical pathway 基本没变；
6. 当前证据只能说 Dense/Hybrid 的 Gold-level metric changes 更明显，
   不能据此证明 embedding-input alignment 是主导机制；
7. 相同 total_chunks=215 不代表相同 chunk boundaries。
```

不能支持：

```text
1. "Dense/Hybrid 变化主要由 Dense input 导致"；
2. "embedding-input alignment 是重要/主导机制"；
3. "词面统计共同机制较弱"；
4. "Dense 提升/下降完全由 truncation 造成"（无 truncation-only
   intervention，chunk boundaries 同时改变）；
5. "消除截断一定改善 Retrieval"（当前 Dense 反而下降，Hybrid 改善）；
6. 任何统计显著性结论（未做显著性检验）。
```

```text
alignment intervention effect != truncation-only causal effect
```

## 11. 负/混合结果说明

本实验不是单边"变好"：Dense 下降、Hybrid 改善、BM25 aggregate
metrics 基本不变（但其 ranking 36/50 变化）。
这是完全有效的干预结果：它证明 aligned chunk-budget 会实质改变
检索行为，且变化方向因策略而异；不调整任何参数。

## 12. 数据来源

- Aligned：`experiments/04fc6d2111a6/`、`b35b1102197e/`、
  `e680cdf278b2/`（各含 index_manifest / retrieval_results /
  retrieval_metrics / result，schema_version=2）
- Historical：`dc220d794578/`、`dbc497c796d5/`、`3c613202e1ed/`
- 结构化数据：[agent_ai_v1_tokenizer_aligned_ablation.json](./agent_ai_v1_tokenizer_aligned_ablation.json)
- 学习笔记：[59-BGE对齐分块与干预实验.md](../../docs/study-notes/59-BGE对齐分块与干预实验.md)
