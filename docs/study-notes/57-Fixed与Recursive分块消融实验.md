# 57 - Fixed 与 Recursive 分块消融实验

> 面向项目作者的学习笔记，配合 G2-ABL-17 正式实验阅读。
> 目标：看完后能自己讲清楚"为什么 RAG 要分块、Fixed 和 Recursive
> 差在哪、为什么换分块策略会同时影响 Dense 和 BM25"。

## 1. 为什么 RAG 要 Chunk

RAG 的实际检索单位通常是"文本片段"，而不是整篇文档。原因不是
"长文档绝对不能整体 Embedding"，而是工程上的取舍：

- 一篇文档可能有几千到几万 token，整体 Embedding 后：
  - 向量只有一个，无法定位"哪一段"回答 Query；
  - 长文本的平均语义会稀释局部关键信息（Attention 聚合后，
    局部强证据被大量无关内容"平均"掉）；
  - 上下文窗口有限，最终喂给 LLM 的也不能是整篇文档。
- 分成 chunk 后：
  - 每个 chunk 是独立检索单元，可以返回"第几个片段"；
  - 命中粒度从 document 细化到 fragment；
  - 但代价是：证据可能被切到不同 chunk，出现 recall 碎片化。

注意：这里说的是"通常"，不是"绝对"。短文档也可以整体入库；是否分块、
分多细，都是实验问题。

## 2. chunk_size 是什么

本项目 `chunk_size=512` 指的是 **token budget**，不是字符数。

TokenCounter 先对原文做 token 统计（本项目对中文用字符估算，英文用
空格分词，详见 study-notes 28/35/36），chunk 组装时以 token 预算为准：

- 达到预算就换块；
- 换块时按 overlap 回退若干 token；
- 输出文本仍是原文的精确子串（不以 token 为单位截断原文，token 只做
  预算计算）。

所以 `chunk_size=512` 的意思更准确说是"每个 chunk 大约占 512 token
的预算"，而不是"512 个字符"。

## 3. overlap 是什么

overlap 是相邻 chunk 之间的重复区域：下一个 chunk 不是从上一个 chunk
结尾处硬切，而是回退 `overlap` 个 token 再开始。

为什么需要 overlap：

- 句子的上下文可能横跨切分点（前半句在 chunk A，后半句在 chunk B）；
- 关键词可能落在切分点附近，重叠可以让它同时出现在两个 chunk；
- 对 Hybrid 检索，overlap 还会让同一证据在 Dense/Sparse 两路都有
  更大机会以"完整表达"被命中。

overlap 太大的问题：

- chunk 数量增多、索引膨胀、检索候选重复度高；
- 同一内容被多次检索到，Top-K 里出现大量重复信息，挤占容量。

overlap 太小的问题：

- 边界处上下文丢失，chunk 语义不完整。

本项目固定 64/512（12.5%），这是当前冻结配置，不在本任务范围内调整。

## 4. FixedSizeChunker

FixedSizeChunker 的行为近似：

```text
从当前位置开始，按 token 窗口连续取内容
→ 达到 budget 就换块
→ 换块时回退 overlap 个 token 再开始
→ 输出原文精确子串
```

它不关心段落、句子、标点。切分点完全由 token 位置决定。

优点：简单、可预期、实现稳定。
缺点：可能在段落中间、句子中间硬切，导致 chunk 内部语义不完整。

## 5. RecursiveChunker

RecursiveChunker 在同一个 token budget 下，先尝试按"更自然的边界"
切分，优先级大致是：

```text
\n\n（段落） → \n（换行） → 。（中文句号） → .（英文句号） → 空格
```

如果按段落边界组装出的块不超过 budget，就用段落边界；如果超了，再
退到下一级分隔符继续切。最终仍然受 token budget 限制。

优点：chunk 更可能包含完整段落/句子，语义边界更自然。
缺点：chunk 长度分布不固定；同一个词项可能因边界选择被分到不同 chunk；
总 chunk 数也会变化。

## 6. 为什么 Recursive 不一定更好

直觉上"语义边界更自然"好像一定更好，但实际不是：

- 边界更自然，但 chunk 长度分布改变（有的短、有的接近满预算）；
- 关键词/证据句可能因为"优先按段落切"被分配进不同 chunk，反而
  改变了 Dense/BM25 的命中；
- chunk 总数变化（本项目 Recursive 215 个，Fixed 237 个）；
- BM25 的词项共现、TF、文档长度统计单位全部随 chunk 改变；
- 这些变化的方向不统一：有的 Case Fixed 赢，有的 Case Recursive 赢。

G2-ABL-17 的真实数据就是证据：

```text
Dense:  6/50 个 Case 的 Hit 状态翻转（Fixed 5 输 1 赢）
BM25:   1/50 翻转（Fixed 1 输）
Hybrid: 4/50 翻转（Fixed 2 赢 2 输）
```

没有任何"Recursive 全面更好"的简单规律。

## 7. 为什么必须固定 Retriever 再比较 Chunker

消融实验的铁律是"一次只改变一个变量"。

如果同时改 chunker 和 retriever，结果变化时无法归因：

```text
指标变了
→ 是 chunk 的问题？还是 retriever 的问题？还是两者交互？
```

所以 ABL-17 的对比方式是：

```text
Recursive Dense / BM25 / Hybrid
Fixed     Dense / BM25 / Hybrid
```

同一 retriever 内部，唯一变量是 chunk_strategy；Corpus、Gold、Query、
Embedding 配置、Top-K、索引构建输入全部一致。每个 formal experiment
仍然使用自己的物理 Workspace 和独立索引实例（不共用索引）。

## 8. 为什么 total_chunks 可以变化

不同 chunk boundary strategy 产生不同 chunk 数量是正常现象：

```text
Recursive: 215
Fixed:     237
```

差异本身是有信息量的实验观察：Fixed 按固定窗口切，会产生更多更短或
更碎（相对自然段落）的块。

公平性要求不是"chunk 数相同"，而是：

```text
同一策略的三个 retriever（Dense/BM25/Hybrid）必须共享同一个
total_chunks
```

ABL-17 中三个 Fixed 实验都是 237，满足前提。

## 9. Chunk strategy 如何影响 Dense

Dense Retrieval 把每个 chunk 做 Embedding，Query 也做 Embedding，
然后按向量相似度取 Top-N。

因此 chunk strategy 改变的是：

```text
Embedding 的表示单位
```

同一个文档，切成不同 chunk，每个 chunk 的向量就不同：

- 若证据句单独成块，向量更聚焦，Query 相似度可能更高；
- 若证据句和大量无关段落混在一个块里，向量被稀释，相似度下降；
- 同一证据被切到两个 chunk 时，任何一边都可能"不够完整"。

ABL-17 中 Dense 是受 chunk 影响最大的策略（6/50 翻转），符合这个直觉。

## 10. Chunk strategy 如何影响 BM25

BM25 是词面检索，它的统计单位也是 chunk：

- TF：词在 chunk 内出现次数；
- 文档长度：chunk 的 token 数；
- 词项集合：chunk 里出现了哪些词。

换 chunk strategy 后：

```text
词项共现关系变了
TF 统计变了
文档长度统计变了
→ BM25 分数和排名全部可能变化
```

例如一段话里同时含 "RRF" 和 "chunk_id"，Recursive 可能把它们放进一个
自然段落块，Fixed 可能把它们切到两个块，于是 BM25 对同时命中两个词的
Query 的打分就完全不同。

这是面试中容易忽略的点：很多人以为"BM25 只跟词有关，跟分块无关"，
实际上 BM25 的统计单位就是 chunk，分块必然影响它。

## 11. Chunk strategy 如何影响 Hybrid

Hybrid 是两个通道先各自取 Top-30，再用 RRF 融合取 Top-5：

```text
Dense Top-30（按 chunk 向量）
        \
         → RRF → chunk_id_asc tie-break → Top-5
        /
BM25 Top-30（按 chunk 词面）
```

chunk strategy 同时改变两路候选，因此 Hybrid 的变化是两路变化的叠加：

- 可能两个通道都更差 → Hybrid 变差；
- 可能一路变好一路变差 → 看 RRF 结果；
- 可能两路都命中了同一个 Gold 文档的不同 chunk（chunk 层不重合），
  RRF 无法合并两路信号 → 这就是 G2-ANALYSIS-14 的 fragmentation。

ABL-17 中 Fixed Hybrid 在 q039 / q047 由失败变成功，在 q012 / q016
由成功变失败，说明 chunk 与融合存在交互。

## 12. Document-level Gold 的证据边界

当前 Gold 是 document-level（`relative_path`），不是 chunk-level。

因此：

```text
某个 Gold 文档被检索到
≠
被检索到的那个 chunk 真的包含回答 Query 的证据
```

ABL-17 只能说：

```text
chunk strategy affects retrieval outcome
```

不能说：

```text
某个具体 chunk boundary 就是失败原因
```

因为我们没有 chunk-level Gold label，无法知道"正确证据"在哪个 chunk、
被切到了哪里。

## 13. 用本次真实 Case 举例

### Case 1：q039（Fixed Hybrid 由失败变成功）

```text
relevant = rag/检索与生成.md

Recursive Hybrid：Final Top-5 无 Gold → Hit=0
Fixed Hybrid：    Final Top-5 有 Gold（first=4）→ Hit=1

Dense: Recursive first=1 → Fixed first=3（仍命中）
BM25:  Recursive first=2 → Fixed first=2（仍命中）
```

有趣的是：两个通道在 Recursive 下都命中了 Gold 文档，但 Hybrid 失败；
换成 Fixed 后 Hybrid 成功。原因很可能与 G2-ANALYSIS-14 的
fragmentation 有关（Recursive 下 Dense/Sparse 命中同一文档的不同
chunk，RRF 无法合并；Fixed 下落点改变）。但"很可能"只是假设，
需要后续在 Fixed 诊断快照上验证。

### Case 2：q013（Fixed Dense 由成功变失败）

```text
relevant = llm/预训练.md

Dense: Recursive Hit=1（first=3）→ Fixed Hit=0
```

同样的 512/64 预算，只换 chunk strategy，Gold 文档就从 Dense Top-5
掉出去了。这直观展示了"证据表达被切到不同 chunk 后，Dense 相似度
下降"的机制，但仍不能直接断言是哪一刀切坏了。

### Case 3：q036（Fixed Dense 的 multi-file Recall 下降）

```text
relevant = 3 个文件
Dense: Recall 0.667 → 0.333（丢失 tool_calling/Function-Calling原理.md）
```

multi-file 场景下，chunk strategy 不仅影响是否命中，还影响命中几个
Gold 文件。只看 Hit 会漏掉这类信息。

## 14. 面试追问

### Q1：Fixed 和 Recursive 有什么区别？

Fixed 按固定 token 窗口连续切；Recursive 优先按 `\n\n → \n → 。 → .
→ 空格` 等语义边界切，最终都受 token budget 限制。两者都保证输出原文
精确子串，区别是切分点的选择策略。

### Q2：为什么不是 chunk 越小越好？

chunk 越小，每个块越聚焦，但：

- chunk 总数膨胀，检索效率下降；
- 单个块可能没有完整上下文（前提、指代、结论被拆开）；
- 证据碎片化，多个相关块需要重新聚合；
- BM25 的 TF/长度统计也随单位变化。

chunk size 是 trade-off，不是单调最优。

### Q3：overlap 为什么不能无限大？

overlap 越大，索引重复内容越多，检索候选重复度高，Top-K 有效容量被
稀释，成本上升；收益（边界上下文保留）有上限。工程上通常取 chunk size
的 10%–20% 左右。

### Q4：为什么换 Chunker 后 BM25 也会变化？

BM25 的统计单位是 chunk：TF、文档长度、词项集合都基于 chunk。切分方式
改变后，同一个词可能出现在不同 chunk、共现关系改变、长度统计改变，
所以 BM25 分数和排名都会变。本项目 BM25 是受影响最小的策略（1/50
翻转），但不等于不受影响。

### Q5：Recursive 一定优于 Fixed 吗？

不一定。ABL-17 的真实结果：

```text
Recursive vs Fixed（同一 retriever）
Dense:  Recursive 明显更好（Hit 0.88 vs 0.80）
BM25:   Recursive 略好（0.98 vs 0.96）
Hybrid: Hit 相同（0.92 vs 0.92），但 Fixed Recall 更高
        （0.9133 vs 0.8933）、MRR/nDCG 更低
```

"更自然的边界"在某些 Case 反而把关键词分配到不同 chunk。必须做实验，
不能凭直觉。

### Q6：如何公平做 Chunk Strategy ablation？

一次只改 chunk_strategy，其余全冻结：

```text
Corpus / Gold / Query / Embedding 配置 / Chunk 配置中的其他字段 /
Top-K / 索引构建输入与相关配置
```

且每个 formal experiment 用独立 Workspace 与独立索引实例；比较同一
strategy 下三个 retriever 是否共享 total_chunks；记录
experiment_id（chunk_strategy 必须进入身份，否则两个不同分块实验会
拿到同一个 experiment_id）。

### Q7：为什么要重建索引？

chunk 变化后，Dense 的 Embedding 单位变了、BM25 的统计单位变了，
旧索引里的 chunk 与 id 映射全部失效。不重建索引就对比 Fixed/Recursive
会产出虚假结果（本项目 G2 早期专门修过这个问题，见 study-notes 37）。

### Q8：total_chunks 改变会带来哪些影响？

- 索引规模、检索候选数量变化；
- Dense/BM25 的统计单位数量变化；
- Top-5 chunk → 文档去重后的覆盖能力变化；
- 但 total_chunks 本身不同不破坏公平性，前提是同一策略的三个
  retriever 保持一致。

## 书面学习要点

1. 分块是 RAG 检索粒度的事实来源：chunk 同时是 Dense 的表示单位和
   BM25 的统计单位，所以 chunk strategy 会同时影响两路检索。
2. Fixed 是"位置决定边界"，Recursive 是"语义边界优先、预算兜底"；
   两者都没有先验的全面优势。
3. 消融的铁律是控制变量：一次只改一个变量，身份里必须记录该变量
   （chunk_strategy 已进入 ExperimentConfig → experiment_id）。
4. 当前 Benchmark 观测：Dense 对 chunk 最敏感（6/50 翻转），BM25 最
   不敏感（1/50），Hybrid 居中（4/50）且出现 rescue/regression 各半。
5. 文档级 Gold 只能证明"chunk strategy affects retrieval outcome"，
   不能证明"某个具体边界是失败原因"；后者需要 chunk-level 证据。

> 本次 50 Case Benchmark 能支持当前数据集上的工程选择，但不能单独证明
> Fixed/Recursive 在其他语料、其他 Query 分布上普遍谁更好。
