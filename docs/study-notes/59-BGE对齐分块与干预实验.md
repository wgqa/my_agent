# 59 - BGE 对齐分块与干预实验

> 面向项目作者的学习笔记，配合 G2-ABL-21 正式 intervention 阅读。
> 目标：从零讲清"为什么 chunk_size=512 还会被 BGE 截断、
> aligned 后为什么正文预算是 510、为什么跑 BM25 作为 control"。

## 1. 为什么两个 512 不一样

`chunk_size=512` 里的 512 是谁的 token？

```text
cl100k 512：
  tiktoken cl100k_base 数出来的 token 预算
  → 只决定"何时换块"

BGE BertTokenizer 512：
  BAAI/bge-small-zh-v1.5 的 max_seq_length
  → 决定"模型最多吃多长输入"
```

两套 tokenizer 的词表、分词算法、special-token 行为都不同。同一段
中英混排文本，cl100k 可能数出 500，BGE 可能数出 550。因此
"Chunker 判定未超 512" 与 "BGE 输入不超过 512" 是两个独立命题。

本项目实测（DIAG-18）：cl100k Recursive 215 个 chunk 中 57 个在
BGE runtime 下超过 512，即 26.51% 会被截断。

## 2. Special Tokens

BERT 类模型输入通常带 [CLS] 和 [SEP]：

```text
[CLS] token1 token2 ... tokenN [SEP]
```

它们也算在输入长度里。判断"会不会被截断"必须用
`add_special_tokens=True` 的最终长度。

当前 runtime 的
`tokenizer.num_special_tokens_to_add(pair=False) = 2`：

```text
model input 512
→ content 预算 = 512 - 2 = 510
```

2 来自运行态读取，不是通用常数；不同模型可能是 1、2 甚至更多。

## 3. Content Budget 与 Overlap Budget

aligned 模式区分：

```text
count_content(text)      # 不含 special tokens，用于切块与 overlap
count_model_input(text)  # 含 special tokens，用于最终校验
```

为什么 overlap=64 不能加 [CLS]/[SEP]？

```text
overlap 的语义是"相邻 chunk 重复的正文内容"
每个 chunk 的 [CLS]/[SEP] 是模型输入层面的固定开销，
不是正文的一部分。
```

如果错误地把 special tokens 算进 overlap，overlap 预算会被 2 个
固定 token 污染，回退位置偏移、正文覆盖不稳定。

## 4. Runtime Contract：三种 Fingerprint 的关系

```text
Preflight contract fingerprint（pre-run）：
  实验开始前，用本地只读 SentenceTransformer 对固定 probe suite
  算 tokenization output 哈希
  → 进入 ExperimentConfig / experiment_id
  → 回答"我声明用的 tokenizer 行为契约是谁"

Formal Pipeline validation：
  正式 Pipeline 创建后，从真正 encode 的模型实例重算同一 contract
  → 与声明逐字段比对，不一致 fail-fast
  → 回答"实际执行与声明是否漂移"

corpus-scoped observed fingerprint（post-index）：
  索引完成后，从正式 vector store 实际 chunks 的 input_ids 算哈希
  → 进入 IndexManifest 顶层
  → 回答"这批真实 chunk 被如何 tokenization"
```

一个管身份、一个管执行、一个管事实。

## 5. 为什么 Counter 与 encode 必须共用 tokenizer instance

DIAG-18 证明：同样是 BertTokenizer、同样是 512，
normalizer 不同（sentence-transformers 加了 Lowercase）会导致
token 数不同。

如果 Counter 用 A tokenizer 切 chunk、encode 用 B tokenizer 建模：

```text
Counter 认为：content=510，OK
encode 实际收到：B 数出 520 → 截断
```

所以 `EmbeddingRuntimeTokenCounter` 必须取
`Pipeline.embedding.get_runtime_tokenizer()`，与 encode 使用同一个
`self._model` 实例；prepare 验证的是 **object identity**，不是
"contract 相同就行"。

## 6. Non-Monotonic Token Count

老式二分假设：

```text
文本越长 → token 越多（单调非减）
```

对 BPE/WordPiece 不一定成立：某段文本加一个字符可能触发重新合并，
token 数反而变少。真实反例：

```text
count(prefix 100) = 509
count(prefix 101) = 513
count(prefix 102) = 510   ← 更长的反而合法
```

单调二分会停在 100，丢掉真正合法的最远 boundary 102。

因此 aligned Counter 使用 correctness-safe 线性扫描，post-condition
只是额外防线；对 37 个文件的语料，正确性优先于微小切块性能。

## 7. 本次正式实验

### 研究假设

```text
把 Recursive Chunk Budget 从 cl100k 换成 embedding_runtime
（512 model-input / 510 content），
把 would-truncate 从 57/215 降到 0，
观察 Dense / BM25 / Hybrid 正式指标变化。
```

### 设计

```text
intervention：chunk_budget_policy 单变量
control：     BM25（对 chunk boundary 也敏感但完全不依赖 Dense）
三策略：      Recursive + Dense / BM25 / Hybrid（top5、RRF60、tie chunk_id_asc）
数据：        corpus 870e5864df67、evaluation 18c1c0470652（37 files / 50 cases）
```

### 结果（正式）

```text
                 cl100k      aligned       delta
Dense Hit        0.88        0.84          -0.04
Dense nDCG       0.7624      0.7078        -0.0545

BM25 Hit         0.98        0.98           0.00
BM25 nDCG        0.8206      0.8064        -0.0143

Hybrid Hit       0.92        0.96          +0.04
Hybrid Recall    0.8933      0.9333        +0.04
Hybrid nDCG      0.7994      0.7959        -0.0035
```

干预成功（would-truncate=0，model-input max=512），但效果分叉：

```text
Dense 变差（Hit -4，q023/q036/q045 loss）
BM25 基本不变（0 rescue / 0 loss）
Hybrid 改善（q039/q047 rescue，0 loss）
```

## 8. 因果边界

```text
alignment intervention effect
!=
truncation-only causal effect
```

为什么 BM25 是 control：

```text
换 budget tokenizer 会同时改变 chunk boundaries、
overlap landing、BM25 词项统计、Dense 表示单位、RRF 候选。

若 BM25 也大幅变化 → 共同机制是 chunk boundary/词面统计；
若 BM25 基本不变 → 变化更可能来自 Dense 输入侧（alignment）。
```

本次：BM25 几乎不动（仅 q033 multi-file Recall -1），Dense/Hybrid
明显变化 → 支持 embedding-input alignment 是重要机制（情况 A）。

仍不能证明"truncation alone"：

```text
要严格归因，需要"只移除截断、不改变 boundary"的 intervention，
以及 chunk-level Gold。
```

## 9. 负 / 混合结果如何解释

本次不是"变好"的单边故事：

```text
Dense 下降、Hybrid 上升、BM25 不变
```

这是完全有效的实验结果，价值在于：

```text
1. 证明 aligned chunk-budget 会实质改变检索行为；
2. 变化方向依赖策略（不是"消除截断必然变好"）；
3. 相同 total_chunks=215 不代表相同 boundaries（文档 ranking
   变化 Dense 47/50、BM25 36/50、Hybrid 37/50）；
4. 为下一轮假设（例如 channel-level 或 chunk-level 分析）提供事实。
```

禁止为了"更漂亮"的结果调参数；负结果与混合结果同样是可复现
Benchmark 的科学产出。

## 10. 面试问答

### Q：为什么 chunk_size=512 还会被 BGE 截断？

因为 512 是 cl100k token 预算，不是 BGE token。两套 tokenizer 对
同一文本计数不同；BGE 计数还包含 [CLS]/[SEP]。本项目 215 个
Recursive chunk 中 57 个在 BGE 下超过 512（26.51%）。

### Q：为什么 aligned 后正文预算是 510？

model input 上限 512 包含 2 个 special tokens（运行时读取），所以
正文 content 预算 = 512 − 2 = 510；保证 content + [CLS]/[SEP] ≤ 512。

### Q：为什么不直接用 tokenizer.decode 做 Chunk？

因为原始文本必须是事实源，Chunk 必须是原文精确 substring。
`decode` 是从 token ids 重建文本，可能改变空白、换行、标点等，
破坏"原文精确子串"契约；tokenizer 只应做预算判断。

### Q：为什么还要跑 BM25？

BM25 是 control：换 budget tokenizer 会同时改变 chunk boundaries
和词面统计。如果 BM25 也大幅变化，说明变化不只在 Dense 输入侧；
如果 BM25 基本不变（本次结果），则更支持 embedding-input
alignment 是重要机制。它帮助区分 general chunk-boundary effect
与 Dense-input-specific effect。

### Q：如果 Dense 提升能否说是截断造成的？

不能。aligned 改变的是整个 chunk-budget intervention（boundaries、
overlap、表示单位同时变化），不是"只移除截断"；要严格归因需要
truncation-only intervention 与 chunk-level Gold。本次 Dense 反而
下降，Hybrid 上升，进一步说明不能做单因果归因。

### Q：为什么同样 215 个 Chunk 也可能是不同实验？

total_chunks 相同只说明数量相同，不说明边界相同。逐 Case 文档
ranking 变化 Dense 47/50、BM25 36/50、Hybrid 37/50，且
`chunk_budget_policy` 已进入 experiment_id，所以两个 215-chunk
实验是不同实验身份、不同 chunk boundaries。

### Q：pre-run fingerprint 和 corpus-scoped fingerprint 有什么区别？

```text
pre-run contract fingerprint：probe suite 的 tokenization 行为哈希，
  进入 ExperimentConfig/experiment_id，声明"我用谁"；
corpus-scoped fingerprint：正式 vector store 实际 chunks 的
  input_ids 哈希，进入 Manifest，证明"这批真实 chunk 如何被 tokenize"。
```

一个回答身份，一个回答执行事实；二者都用同一 runtime tokenizer，
但输入不同、时机不同、用途不同。

## 书面学习要点

1. 两个 512 是两把不同的尺子；aligned 后 content budget = 510
   （512 − runtime special overhead）。
2. overlap 永远是 content tokens，special tokens 不进入 overlap。
3. 身份（pre-run contract）、执行（Pipeline validation）、事实
   （corpus-scoped fingerprint）三层必须分开且互相绑定。
4. Counter 与 encode 必须共用同一 tokenizer 对象；non-monotonic
   token count 需要 correctness-safe 搜索。
5. 正式干预结果：Dense 下降、BM25 基本不变、Hybrid 改善；
   alignment intervention effect ≠ truncation-only causal effect；
   混合结果与负结果同样是有效实验结果。

> 本次 50 Case Benchmark 支持"aligned chunk-budget 会实质改变检索
> 行为、且变化集中在 Dense 依赖路径"这个结论；不能单独证明
> "消除截断必然提升检索"或"Dense 下降就是截断消失造成的"。
