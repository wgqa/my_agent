# Gate 2 Final Review：可复现评测体系与 Retrieval 证据冻结

> G2-CLOSE-22。本文按"问题 → 证据 → 结论 → 边界"组织，不是时间线
> changelog。所有指标来自已冻结正式 Artifact，未手算新 metric。

## 1. Gate 2 要解决什么

"RAG 能返回结果"不等于"RAG 可以做实验"。

一个能跑的 demo 通常缺三样东西：

```text
可复现身份：同配置重跑必须是同一个实验，不能靠运气
可信数据：语料和 Gold 必须冻结、可校验、不能偷偷变
可验证执行：声明的配置必须等于实际运行的行为
```

Gate 2 建立的正式链路：

```text
ExperimentConfig
→ experiment_id
→ ExperimentWorkspace（独立目录 / 独立索引）
→ ExperimentCorpus（corpus_id / SHA-256 / size）
→ index_manifest（Manifest v2）
→ RetrievalEvaluationSet（evaluation_set_id）
→ retrieval_results
→ retrieval_metrics（Hit/Recall/MRR/nDCG）
→ ExperimentResult（result_id）
```

其中最重要的原则：

```text
declared config（声明配置）
vs
actual runtime behavior（实际运行行为）
```

必须绑定：实验身份不能只相信 YAML 字符串，还要验证 Pipeline 实际
使用的 Retriever 类型、tokenizer 对象、chunk counter、向量库路径等。

## 2. 冻结数据集身份（Benchmark v1）

```text
corpus_id         = 870e5864df67
file_count        = 37

evaluation_set_id = 18c1c0470652
case_count        = 50

43 single-document cases
7  multi-document cases
58 Gold document obligations
```

Gold 已冻结。后续 Gate 3 除发现客观 annotation bug 并明确版本化外，
不得为了让新 Agent 指标更漂亮修改 Gold。

## 3. 正式核心实验矩阵

### 3.1 Recursive + cl100k_content_v1

```text
Dense (dc220d794578 / c2d4ec845d9e):
  Hit@5 0.88 | Recall@5 0.8633333333 | MRR 0.7483333333 | nDCG@5 0.7623809500

BM25 (dbc497c796d5 / acd92171966d):
  Hit@5 0.98 | Recall@5 0.9533333333 | MRR 0.7873333333 | nDCG@5 0.8206430540

Hybrid (3c613202e1ed / e27141a2b63e):
  Hit@5 0.92 | Recall@5 0.8933333333 | MRR 0.7866666667 | nDCG@5 0.7993602602
```

### 3.2 Fixed + cl100k_content_v1

```text
Dense (5bc53c69a412 / fe78ad8da137):
  Hit@5 0.80 | Recall@5 0.7866666667 | MRR 0.6716666667 | nDCG@5 0.6896493982

BM25 (9f5572b49b9d / 9d0e33ed6970):
  Hit@5 0.96 | Recall@5 0.9333333333 | MRR 0.7583333333 | nDCG@5 0.7892026423

Hybrid (0baf05e91fca / 63508f04407c):
  Hit@5 0.92 | Recall@5 0.9133333333 | MRR 0.7600000000 | nDCG@5 0.7914688615
```

### 3.3 Recursive + embedding_runtime_model_input_v1（G2-ABL-21）

```text
Dense (04fc6d2111a6 / 805658b71e76):
  Hit@5 0.84 | Recall@5 0.8400000000 | MRR 0.6696666667 | nDCG@5 0.7078465372

BM25 (b35b1102197e / 812d4d4e2bd2):
  Hit@5 0.98 | Recall@5 0.9433333333 | MRR 0.7850000000 | nDCG@5 0.8063855324

Hybrid (e680cdf278b2 / 26327c177e37):
  Hit@5 0.96 | Recall@5 0.9333333333 | MRR 0.7633333333 | nDCG@5 0.7958963239
```

## 4. Gate 2 Benchmark Winner

在当前 50-case document-level Benchmark 上，主要 Hit/Recall/nDCG
指标的最佳组合：

```text
Recursive + BM25 + cl100k_content_v1
（dbc497c796d5 / acd92171966d）
```

精确比较依据（Hit / Recall / nDCG 三列均为当前最高）：

```text
               Hit@5   Recall@5   nDCG@5
Rec BM25      0.98    0.953333    0.820643   ← best
Aligned BM25  0.98    0.943333    0.806386
Rec Hybrid    0.92    0.893333    0.799360
Aligned Hybrid 0.96   0.933333    0.795896
Rec Dense     0.88    0.863333    0.762381
```

补充说明（已由现有 Artifact 校验）：

```text
Rec BM25 Hit@5 = 0.98 为当前核心实验矩阵并列最高（Aligned BM25 同为
0.98）；
Recall@5 / MRR / nDCG@5 为当前核心实验矩阵最高。
```

边界限定：

```text
当前 37 份技术文档
当前 50-case Gold
Top-5 chunk retrieval（文档级指标）
当前技术文档语料
```

不写"BM25 永远比 Dense 好"或"Hybrid 没用"。

## 5. Gate 3 冻结 Retrieval Reference

### Primary retrieval reference

```text
Recursive
cl100k_content_v1
BM25
top_k=5
sparse_candidate_k=30

experiment_id = dbc497c796d5
result_id     = acd92171966d
```

理由：当前 Benchmark 上最强的 document-level retrieval reference，
作为 Query Decomposition / Adaptive Retrieval 的稳定 control。

### Hybrid reference

```text
Recursive + cl100k_content_v1 + Hybrid
experiment_id = 3c613202e1ed
result_id     = e27141a2b63e
```

用途：后续 Adaptive Retrieval 需要在 lexical / dense / hybrid 间做
策略选择时的 Hybrid control。不得删除或降格 Hybrid。

必须区分：

```text
best benchmark reference（当前最强参考）
!=
系统永远只允许 BM25（产品决策）
```

## 6. 最重要的工程发现

### RRF determinism

原因：`set` 遍历顺序无契约，score-only stable sort 在同分时继承 set
输入顺序；不同进程 / PYTHONHASHSEED 下平局候选顺序可能不同（q004
真实出现 (2,8) vs (8,2) 完全同分）。

最终 contract：

```text
rrf_score DESC
→ chunk_id ASC
```

且该策略进入 ExperimentConfig / experiment_id。

### Runtime retriever binding

声明 `retriever_strategy="bm25"` 不够：必须证明实际 Pipeline 的
retriever 是 `BM25OnlyRetriever`（isinstance，而非字符串比较）。
否则"实验身份撒谎"：config 写 bm25、实际跑 simple，指标却挂到
bm25 名下。

### Sparse integrity

```text
BM25 doc_count == vector_store_count == total_chunks
```

是正式实验完整性的一部分：vector count 只证明 Chroma 有 215 条，
不能证明 BM25 索引也有 215 条；两者是不同数据结构。

### Offline vs Formal

离线 channel ablation 快、成本低，但只是 counterfactual 假设生成；
正式实验必须用独立 Workspace / Index 复现，且 formal/offline 逐
Case parity（Dense/BM25 均为 50/50）通过后才可采信。

## 7. 主要 Retrieval 科学结论

### C1

在 canonical Recursive + cl100k_content_v1 三策略正式对照中：

```text
BM25 > Hybrid > Dense
```

在 Hit@5 / Recall@5 / nDCG@5 上成立。作用域限定为：当前 37 文档、
当前 50-case Gold、Top-5 chunk retrieval、document-level 指标。

注意：C1 不是所有 chunk policy / strategy 组合的全局规律。例如
Fixed + cl100k 下 Hybrid nDCG（0.7914688615）高于 BM25
（0.7892026423），因此该排序只对 canonical Recursive + cl100k
三策略对照成立。

### C2

Chunk strategy 有实质影响：同预算下切换 Fixed/Recursive 大量改变
检索结果；Recursive 当前总体优于 Fixed。但不能因此声称某个具体
boundary 是失败的直接原因（无 chunk-level Gold）。

### C3

Hybrid failure 不是简单的"两个 channel 都没找到"：H1 未获支持。
多数失败 Gold 已进入 Dense/BM25 候选，问题在融合/排名层。

### C4

Chunk-level RRF fragmentation 是 plausible mechanism：同一 Gold
document 被 Dense/BM25 命中不同 chunk 时，chunk-level RRF 不会自动
汇聚两路信号。因缺 chunk-level Gold，保持 plausible / unverified。

### C5

Multi-document query incompleteness 是真实问题（q031/q034/q036
等），是 Gate 3 Query Decomposition 的直接动机之一。不能说 Gate 3
一定能解决。

## 8. Tokenizer Alignment 结论（三层）

```text
Level 1：cl100k budget vs BGE runtime tokenizer mismatch
  → confirmed（两套 tokenizer 计数不可互换，BGE/cl100k 比值
    max ≈ 1.38）

Level 2：原 Recursive cl100k baseline 中实际 BGE truncation
  57 / 215 = 26.51%（Fixed 71 / 237 = 29.96%）
  → confirmed（实际 SentenceTransformer runtime contract）

Level 3：这些 truncation 是否直接导致 retrieval failure
  → unverified（无 chunk-level Gold / intervention-only 实验）
```

Intervention 总结（G2-ABL-21）：

```text
aligned: 57 / 215 → 0 / 215

结果：
  Dense ↓（Hit 0.88→0.84）
  BM25 aggregate ≈ stable（Hit 0.98→0.98，ranking 36/50 变化）
  Hybrid Hit/Recall ↑（0.92/0.8933 → 0.96/0.9333）

三策略 document rankings 大量变化
（Dense 47/50、BM25 36/50、Hybrid 37/50）
```

结论：

```text
alignment intervention has strategy-dependent effect

alignment intervention effect
!=
truncation-only causal effect
```

## 9. Gate 2 失败 Case Freeze

后续 Gate 3 regression / qualitative inspection set（不改变 Gold）：

```text
q013 / q019 / q039 / q047：原 canonical Hybrid Hit failures
q031 / q034 / q036：multi-document incomplete recall cases
```

Gate 2 当前状态：

```text
q013：Hybrid 0（Dense cl100k hit / BM25 miss / aligned 后仍 Hybrid 0）
q019：Hybrid 0（BM25-only hit，RRF 未保留进 Top-5）
q039：canonical Hybrid 0；Fixed Hybrid 1；aligned Hybrid 1（rescue）
q047：canonical Hybrid 0；Fixed Hybrid 1；aligned Hybrid 1（rescue）
q031：canonical Hybrid Recall 0.5（缺 rag/文档处理.md）
q034：canonical Hybrid Recall 0.5（缺 rag/高级RAG.md）
q036：canonical Hybrid Recall 0.667（缺 Function-Calling原理.md）
```

不再做新诊断。

## 10. Gate 3 Evaluation Contract

后续 Agent/Retrieval 改进不能只看"感觉回答更好"，至少继续保留：

```text
Hit@5
Recall@5
MRR
nDCG@5
```

Query Decomposition 必须重点看 multi-document Recall。Gate 3 可以
新增 Agent-specific metrics，但不得丢掉 Gate 2 retrieval metrics，
否则前后不可比较。

## 11. 数据来源

- 冻结结构化数据：[gate2_freeze.json](./gate2_freeze.json)
- 学习笔记：[60-Gate2评测体系与RAG实验方法总结.md](../study-notes/60-Gate2评测体系与RAG实验方法总结.md)
- 详细消融报告：agent_ai_v1_channel_ablation / chunk_strategy_ablation /
  tokenizer_aligned_ablation（docs/experiments/ 下）
