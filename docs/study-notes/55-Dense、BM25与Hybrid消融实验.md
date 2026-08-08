# Dense、BM25 与 Hybrid 消融实验（G2-ABL-15）

> 2026-08-08 — 595 → 604 tests
> 消融实验的价值不是"证明我的方案最好"，而是搞清楚每个组件
> 各自贡献多少、组合后是加分还是互相拖累。

## 1. Dense Retrieval 原理

Dense Retrieval 把 query 和文档都编码成向量，用向量相似度（余弦/
内积）检索：

```text
query → embedding → 与索引中所有 chunk 向量比较相似度
→ 按相似度排序
```

优点是语义匹配：query 和文档用词不同但意思相近也能命中。
缺点是依赖 Embedding 质量，且对精确词法（专有名词、代码符号、
版本号）不敏感。

本项目：BGE-small-zh-v1.5，HNSW 向量库，`dense_candidate_k=30`。

## 2. BM25 Retrieval 原理

BM25 是词法检索：对 query 分词，统计每个词在文档中的词频（TF）与
逆文档频率（IDF），按权重打分：

```text
score(q, d) = Σ IDF(t) * (tf(t,d)*(k1+1)) / (tf(t,d) + k1*(1-b+b*|d|/avgdl))
```

IDF 让"稀有词"权重更高；长度归一化避免长文档天然高分。
优点是精确、可解释、对专有名词/代码/术语命中稳定；缺点是无法
处理同义改写。

本项目：自实现 BM25Index（jieba 分词），`sparse_candidate_k=30`。

## 3. 两者分别擅长什么

```text
Dense：语义相近、改写、跨词面
BM25：精确词、术语、代码符号、专有名词、数字/版本
```

技术文档/代码语料往往充满专有名词（LangGraph、MCP、RRF、DPO），
因此 BM25 可能系统性更强——这正是 G2-ABL-15 的真实结果。

## 4. 为什么原始 score 不能直接比较

两路分数是不同物理量：

```text
Dense：余弦距离/相似度，范围 [0,1] 附近
BM25 ：无上界的加权词频和
```

直接相加需要未知的归一化/加权，等于引入隐藏超参；同一
embedding 的 0.9 与 BM25 的 9.0 没有可比意义。

## 5. RRF 为什么用 rank

RRF 只使用排名：

```text
RRF(d) = Σ 1/(k + rank_i(d))
```

排名把两路分数统一到同一量纲（第几名），不需要归一化分数；
k 只做平滑，不改变相对排序（本项目 k=60）。

代价：丢弃分数强度信息；同分时必须有确定性 tie-break
（本项目 `chunk_id ASC`，见 study-notes 53）。

## 6. 什么叫 ablation study

Ablation = 消融：从完整系统里移除/隔离某个组件，观察指标变化。

```text
完整系统：Dense + BM25 + RRF
消融：只看 Dense、只看 BM25、再看 Hybrid
```

目的：判断每个组件的边际贡献，而不是只看整体好坏。

## 7. 为什么一次只改变一个变量

如果同时改两个变量，指标变化无法归因：

```text
改 A 又改 B → 结果变了，不知道是谁造成的
```

所以消融要：

```text
控制其余全部相同，只切换一个通道
```

本项目连 Query、Chunk、索引、Embedding 都完全一致，只切换
"用哪个通道的结果"。

## 8. offline ablation 与 formal experiment 的区别

offline / counterfactual ablation：

- 复用已保存的 channel candidates，不再跑检索；
- 优点：零二次随机性，Query/Chunk/索引完全一致；
- 缺点：没有独立正式身份（不是 `ExperimentConfig(retriever_strategy=...)`
  跑出来的三个 ExperimentResult）。

formal experiment：

- 每个策略单独通过 `run_experiment()` 得到自己的 manifest/results；
- 有独立 experiment_id，可被正式审计。

结论可以先用 offline 快照，正式结论需要 formal 确认。

## 9. Hit / Recall / MRR / nDCG 在三种策略比较中分别怎么看

```text
Hit@5   ：至少命中一个 Gold 文件（二值）
Recall@5：命中的唯一 Gold 文件比例（集合语义）
MRR     ：第一个相关文件的排名倒数（顺序敏感）
nDCG@5  ：按位置折损的相关性增益（顺序敏感）
```

比较时：

- Hit/Recall 看"有没有召回"；
- MRR/nDCG 看"排在多前"；
- multi-file Case 必须看 Recall，不能只看 Hit。

## 10. rescue / regression Case 为什么比宏平均更有价值

宏平均会把"修复 4 个、损失 3 个"折叠成一个数字，掩盖方向性：

```text
rescue   = Hybrid 命中而某单通道失败的 Case
regression = Hybrid 失败而某单通道成功的 Case
```

只有逐 Case 的 rescue/regression 才能回答：

```text
Hybrid 的净价值是正还是负？
它到底在修什么、又弄坏了什么？
```

本任务：Hybrid vs Dense 修复 4 / 损失 2；Hybrid vs BM25 修复 0 /
损失 3。

## 11. 用本次真实 q019 / q039 做案例

### q019

```text
Dense-only：失败
BM25-only ：成功（Gold 在 Sparse rank 2 → 文档 rank 2，MRR=0.5）
Hybrid    ：失败（fusion regression，sparse）
```

含义：BM25 已经把这个 Case 的 Gold 放在 Top-5 内，Hybrid 的 RRF
融合反而把它挤出去了。

### q039

```text
Dense-only：成功（Gold 文档 rank 1，Recall 1.0，MRR 1.0）
BM25-only ：成功（Gold 文档 rank 2，Recall 1.0，MRR 0.5）
Hybrid    ：失败
```

含义：两个单通道在文档级都成功，Hybrid 却完全丢失——这是
chunk-level fusion fragmentation 的最强案例（两路支持落在同一
文档的不同 Chunk，RRF 无法合并）。

## 12. 大厂面试追问与参考答案

### Q：Dense 和 BM25 各有什么优缺点？

Dense 语义强、对改写好；BM25 精确强、可解释、对术语/代码稳。

### Q：为什么不能直接加两个分数？

量纲和分布不同，需要未知归一化，等于隐藏超参；RRF 用 rank 规避
了这一点。

### Q：RRF 有什么缺点？

丢弃分数强度；同分需要确定性 tie-break；chunk 级融合无法聚合
同一文档不同 chunk 的跨通道信号。

### Q：怎么做 ablation 才不会误导？

一次只改一个变量、其余完全一致；报告 rescue/regression 而不是
只报宏平均；明确 offline 与 formal 的边界。

### Q：如果 BM25-only 比 Hybrid 还好，是不是说明 RRF 没用？

不能直接这么说。它说明在这份语料 + 这组参数下，Hybrid 相对
BM25 是净损失；需要先理解为什么（融合丢失、candidate_k、reranker
链路），再设计正式对比实验，而不是删除 Hybrid。

### Q：rescue/regression 怎么定义？

按 Hit：Hybrid 命中且至少一个单通道失败 = rescue；Hybrid 失败且
至少一个单通道成功 = regression；multi-file 还要单独比较 Recall。

## 本次真实结论

```text
Dense：Hit 0.88 / Recall 0.8633 / MRR 0.7483 / nDCG 0.7624
BM25 ：Hit 0.98 / Recall 0.9533 / MRR 0.7873 / nDCG 0.8206
Hybrid：Hit 0.92 / Recall 0.8933 / MRR 0.7867 / nDCG 0.7994

all_success 42；hybrid_rescue 4（全 rescues_dense）；
fusion_regression 4；all_fail 0；recall_regression 2。
Hybrid vs Dense：修复 4 / 损失 2
Hybrid vs BM25 ：修复 0 / 损失 3
```

这是 offline / counterfactual 结果，不是三个独立正式实验。
