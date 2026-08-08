# Fixed vs Recursive Chunk Strategy Formal Ablation（G2-ABL-17）

> 正式实验报告，数据来源为六个独立 `ExperimentRunner.run_experiment()` 结果。
> 本任务只改变 `chunk_strategy: recursive → fixed`，其余实验变量全部冻结。

## 1. 为什么比较 Fixed / Recursive

G2-ABL-16 已经正式确认当前 Benchmark 上 Recursive 512/64 下
Dense / BM25 / Hybrid 三套结果。但 Recursive 是默认配置，我们并不知道
"按语义边界优先组装" 的分块方式本身对 Retrieval 指标有多大影响。

本任务回答的问题是：

> 在相同 512 token chunk_size、64 token overlap、相同 Corpus、Gold、
> Embedding 和 Retriever 参数下，FixedSizeChunker 与 RecursiveChunker
> 对 Retrieval 指标有什么影响？

这不是证明 Recursive 一定更好，而是用正式实验记录真实差异。

## 2. 两者原理区别

两者共用同一套 TokenCounter 与预算语义：

- `chunk_size=512` 是 token budget；
- `chunk_overlap=64` 是 token overlap budget；
- 每个 chunk 文本都是原文的精确子串。

主要区别在切分方式：

| 策略 | 切分行为 |
|------|---------|
| Fixed | 按 token 窗口连续切，达到预算即换块，overlap 回退 |
| Recursive | 优先按 `\n\n` → `\n` → `。` → `.` → 空格等边界切分，再在同一 token budget 下组装 |

因此这是一组真正的 chunk boundary strategy 对比：词项分布、chunk 长度
分布、chunk 数量都会变化，进而同时影响 Dense（Embedding 表示单位）、
BM25（词项共现 / TF / 文档长度统计单位）和 Hybrid（两路候选 + RRF）。

## 3. 控制变量

三个 Fixed 实验统一：

```text
corpus_id          = 870e5864df67
evaluation_set_id  = 18c1c0470652
embedding_provider = bge
embedding_model    = BAAI/bge-small-zh-v1.5
chunk_strategy     = fixed
chunk_size         = 512
chunk_overlap      = 64
top_k              = 5
dense_candidate_k  = 30
sparse_candidate_k = 30
rrf_k              = 60
rrf_tie_breaker    = chunk_id_asc
```

仅分别改变 `retriever_strategy`：

```text
agent-ai-v1-fixed-dense-baseline-001   （simple）
agent-ai-v1-fixed-bm25-baseline-001    （bm25）
agent-ai-v1-fixed-hybrid-baseline-001  （hybrid）
```

Recursive 对照组为既有正式结果：`dc220d794578`（Dense）、
`dbc497c796d5`（BM25）、`3c613202e1ed`（Hybrid）。

## 4. 正式实验身份

| 实验 | experiment_id | retrieval_run_id | metrics_run_id | result_id |
|------|---------------|------------------|----------------|-----------|
| Fixed Dense | `5bc53c69a412` | `46bc500a8aa8` | `4b70a236d143` | `fe78ad8da137` |
| Fixed BM25 | `9f5572b49b9d` | `fdd56004f4fb` | `6023c5970077` | `9d0e33ed6970` |
| Fixed Hybrid | `0baf05e91fca` | `f90997ad1065` | `71325768a942` | `63508f04407c` |

三个 Fixed 实验身份彼此不同，且与对应 Recursive 实验
（`dc220d794578` / `dbc497c796d5` / `3c613202e1ed`）全部不同，
因为 `chunk_strategy` 已进入 ExperimentConfig 稳定身份序列化。

## 5. 数据硬校验

三个 Fixed 实验均满足：

```text
corpus_id         = 870e5864df67
evaluation_set_id = 18c1c0470652
file_count        = 37
case_count        = 50
top_k             = 5
```

`total_chunks` 三者一致：

```text
Fixed Dense  = 237
Fixed BM25   = 237
Fixed Hybrid = 237
（Recursive 对照 = 215）
```

Fixed 与 Recursive 的 chunk 数量不同是 chunk boundary strategy 的正常
实验结果；Fixed 三套实验内部完全一致，满足对比前提。

Sparse Integrity（G2-ABL-16-R1 契约首次在新正式 BM25 实验上验证）：

```text
Fixed BM25:   sparse_index_count = 237 == vector_store_count = 237 == total_chunks = 237
Fixed Hybrid: sparse_index_count = 237 == vector_store_count = 237 == total_chunks = 237
Fixed Dense:  sparse_index_count = null（Dense-only 不依赖 BM25，契约允许）
```

契约闭合：未来 BM25 / Hybrid 正式 Manifest 不再出现
`sparse_index_count = null`。

## 6. 2×3 正式指标矩阵

```text
                    Hit@5   Recall@5   MRR       nDCG@5
Recursive Dense     0.88    0.863333   0.748333  0.762381
Fixed     Dense     0.80    0.786667   0.671667  0.689649

Recursive BM25      0.98    0.953333   0.787333  0.820643
Fixed     BM25      0.96    0.933333   0.758333  0.789203

Recursive Hybrid    0.92    0.893333   0.786667  0.799360
Fixed     Hybrid    0.92    0.913333   0.760000  0.791469
```

Fixed − Recursive（absolute delta）：

```text
Dense:  Hit -0.08 | Recall -0.076667 | MRR -0.076667 | nDCG@5 -0.072732
BM25:   Hit -0.02 | Recall -0.020000 | MRR -0.029000 | nDCG@5 -0.031440
Hybrid: Hit  0.00 | Recall +0.020000 | MRR -0.026667 | nDCG@5 -0.007891
```

观测事实：

- Dense 受 chunk strategy 影响最大：四项指标全部下降；
- BM25 受影响最小：只损失 1 个 Case（q045）；
- Hybrid 的 Hit 不变（0.92），Recall 反而上升 +0.02，但 MRR / nDCG 下降；
- 当前 6 个组合中 Recursive BM25 四项指标全部最高。

以上均为当前 50 Case Benchmark 上的 observed result，未做统计显著性检验，
不使用"显著优于"类表述。

## 7. Case-level rescue / regression

按 Hit@5 逐 Case 比较 Recursive → Fixed：

```text
                 fixed_rescue  fixed_regression  unchanged_success  unchanged_failure
Dense            1             5                 39                 5
BM25             0             1                 48                 1
Hybrid           2             2                 44                 2
```

具体 Case：

```text
Dense:  rescue = [q040]
        regression = [q013, q020, q030, q037, q041]
BM25:   rescue = []
        regression = [q045]
Hybrid: rescue = [q039, q047]
        regression = [q012, q016]
```

文档级 ranking 完全一致的比例：

```text
Dense  3 / 50
BM25  14 / 50
Hybrid 10 / 50
```

即使 BM25 的 Hit 只差 1 个 Case，其 Top-5 chunk 组合与文档排序也大量
改变（50 个 Case 中只有 14 个文档排序完全相同），说明 chunk strategy
改变的是细粒度候选，而不是只有胜负翻转的 Case 才有意义。

## 8. Multi-file Recall

7 个 multi-file Case（q031–q038，共 17 个 relevant obligations）：

| Case | relevant n | Dense（rec→fix） | BM25（rec→fix） | Hybrid（rec→fix） |
|------|-----------|------------------|-----------------|-------------------|
| q031 | 2 | 1.000 → 1.000 | 0.500 → 0.500 | 0.500 → **1.000** |
| q032 | 2 | 1.000 → 1.000 | 1.000 → 1.000 | 1.000 → 1.000 |
| q033 | 2 | 1.000 → 1.000 | 1.000 → 1.000 | 1.000 → 1.000 |
| q034 | 2 | 1.000 → 1.000 | 1.000 → 1.000 | 0.500 → **1.000** |
| q035 | 2 | 0.500 → **1.000** | 1.000 → 1.000 | 1.000 → 1.000 |
| q036 | 3 | 0.667 → **0.333** | 0.667 → 0.667 | 0.667 → 0.667 |
| q038 | 2 | 1.000 → 1.000 | 0.500 → 0.500 | 1.000 → 1.000 |

汇总：

```text
                 Recall up  Recall down  Recall equal
Dense            2（q035, q040*）  6（5 个 Hit regression + q036）  42
BM25             0          1（q045）                49
Hybrid           4（q031, q034, q039*, q047*）  2（q012, q016）      44
```

（带 * 的是单文件 Case，其 Recall 变化与 Hit 翻转一致。）

值得注意：Fixed 对 Hybrid 的 multi-file 覆盖是改善的（q031 / q034 的
Recall 从 0.5 升到 1.0），但 Dense 的 q036 从 0.667 降到 0.333。

## 9. 7 个重点 Case

```text
q013（relevant: llm/预训练.md）
  Dense:  Recursive Hit=1（first=3）→ Fixed Hit=0（缺失）   【regression】
  BM25:   Recursive Hit=0 → Fixed Hit=0
  Hybrid: Recursive Hit=0 → Fixed Hit=0

q019（relevant: llm/Transformer架构-03-训练推理与高效Attention.md）
  Dense:  Recursive Hit=0 → Fixed Hit=0
  BM25:   Recursive Hit=1（first=2）→ Fixed Hit=1（first=2）
  Hybrid: Recursive Hit=0 → Fixed Hit=0
  （BM25 rank 2 Gold 没有转化为 Hybrid Final 命中，Fixed 未改变该结论）

q039（relevant: rag/检索与生成.md）
  Dense:  Recursive Hit=1（first=1）→ Fixed Hit=1（first=3）
  BM25:   Recursive Hit=1（first=2）→ Fixed Hit=1（first=2）
  Hybrid: Recursive Hit=0 → Fixed Hit=1（first=4）   【rescue】

q047（relevant: llm/Transformer架构-04-采样与工程联系.md）
  Dense:  Recursive Hit=0 → Fixed Hit=0
  BM25:   Recursive Hit=1（first=1）→ Fixed Hit=1（first=1）
  Hybrid: Recursive Hit=0 → Fixed Hit=1（first=2）   【rescue】

q031（relevant: rag/文档处理.md, rag/检索与生成.md）
  Dense:  Recall 1.000 → 1.000；BM25: 0.500 → 0.500
  Hybrid: Recall 0.500 → 1.000（Fixed 补回 rag/文档处理.md）  【recall 改善】

q034（relevant: rag/检索与生成.md, rag/高级RAG.md）
  Dense:  Recall 1.000 → 1.000；BM25: 1.000 → 1.000
  Hybrid: Recall 0.500 → 1.000（Fixed 补回 rag/高级RAG.md）  【recall 改善】

q036（relevant: prompt/提示工程高级技巧.md, rag/文档处理.md,
      tool_calling/Function-Calling原理.md）
  Dense:  Recall 0.667 → 0.333（丢失 tool_calling/Function-Calling原理.md）
          【recall regression】
  BM25:   Recall 0.667 → 0.667；Hybrid: Recall 0.667 → 0.667
```

q039 是 G2-ANALYSIS-14 中确认的 same-document / different-chunk
fragmentation 代表 Case（Recursive 下 Dense rank1 与 Sparse rank2 落在
同一 Gold 文档的不同 chunk）。换用 Fixed 后 Hybrid 在该 Case 由失败变为
成功（first=4），这说明 chunk boundary 会改变两路信号的落点，进而改变
RRF 结果；但不能据此断言某个具体边界是失败原因（仍无 chunk-level Gold
label）。

## 10. H3 证据更新（拆分 H3a / H3b）

原 H3 是机制/因果假设：

> Chunk 边界让 Gold 文档中的目标证据表达被削弱。

ABL-17 只能证明"切换 Fixed / Recursive 会实质改变 Retrieval
outcome"，不能证明原机制命题。为避免通过改写假设来升级证据，本任务
把 H3 拆成两个命题，分别给出状态。

### H3a：Chunk strategy materially affects retrieval outcome

- **状态**：supported（当前 50 Case Benchmark）
- 证据（本任务正式实验）：
  - 同 512/64 预算下仅切换 Fixed/Recursive，Dense 有 6/50 个 Case
    的 Hit 状态翻转（5 个 regression、1 个 rescue），BM25 1/50，
    Hybrid 4/50（2 个 rescue、2 个 regression）；
  - 文档级 ranking 完全一致的比例很低（Dense 3/50、BM25 14/50、
    Hybrid 10/50），说明候选组合被系统性改变。

### H3b（原机制假设）：特定 chunk boundary 会削弱目标证据的可检索表达

- **状态**：plausible / currently unverified
- 说明：Fixed Hybrid 在 q039 / q047 由失败变成功，Fixed Dense 在
  q013 / q020 / q030 / q037 / q041 由成功变失败，方向并不一致——
  不存在 "Recursive 一定更好" 的简单规律；由于 Gold 是
  document-level 且没有 chunk-level Gold label，我们只能说 chunk
  strategy 改变了 retrieval outcome，不能宣称"某个具体 chunk
  boundary 削弱了目标证据"。

H1/H2/H4/H5 在本任务中没有直接证据升级（本任务不产生新的
channel-level diagnostic），保持 G2-ABL-15 后状态不变。

## 11. 当前 Benchmark 上的最佳组合

按四项指标综合，当前 6 个正式组合中：

```text
Recursive BM25：Hit=0.98, Recall=0.953333, MRR=0.787333, nDCG@5=0.820643
```

四项全部最高。其次为 Recursive Hybrid（Hit=0.92, Recall=0.893333,
MRR=0.786667, nDCG@5=0.799360）与 Fixed Hybrid（Hit=0.92,
Recall=0.913333, MRR=0.760000, nDCG@5=0.791469）。

这只是当前 50 Case 技术文档语料上的 observed result，不构成"BM25 /
Recursive 在其他语料上普遍更优"的普遍规律。

## 12. 结论适用范围

- 结论仅覆盖：37 份技术文档、50 条 Gold、BGE-small-zh-v1.5、
  512/64 token 预算、top5、Dense30/Sparse30/RRF60、chunk_id_asc
  tie-break 的配置空间；
- 未做统计显著性检验；
- 未做 chunk_size / overlap 扫描；
- 没有 chunk-level Gold label，所有结论都是 document-level；
- Fixed 与 Recursive 的 total_chunks（237 vs 215）本身是实验观察，
  不是公平性缺陷。

## 13. 下一实验假设（只提出，不执行）

- H6：chunk strategy 与 channel fusion 存在交互——Fixed 改变两路
  Gold chunk 落点后，Hybrid 在 q039/q047 由失败变成功；值得在后续
  Fixed 诊断快照上验证 fragmentation 类别分布是否变化。
- H7：Dense 对 chunk boundary 更敏感（6/50 Case 翻转 vs BM25 1/50），
  可能与 Embedding 表示单位变化有关；需要 channel-level 证据，不能
  仅凭文档级指标断言。
- H8：Recursive BM25 的 0.98 Hit 在当前语料上接近饱和，chunk 消融
  区分度低；后续应优先在 Hybrid / Dense 路径上观察 chunk 影响。

以上均为待验证假设，本轮不执行。

## 14. 数据来源

- `experiments/5bc53c69a412/agent-ai-v1-fixed-dense-baseline-001/`
- `experiments/9f5572b49b9d/agent-ai-v1-fixed-bm25-baseline-001/`
- `experiments/0baf05e91fca/agent-ai-v1-fixed-hybrid-baseline-001/`
- Recursive 对照组：`dc220d794578` / `dbc497c796d5` / `3c613202e1ed`
- 指标复算使用 `evaluation/metrics.py` 的正式数学，逐 Case 数据来自
  各实验 `retrieval_results.json`（Top-5 chunk → first-hit 文档去重）。
