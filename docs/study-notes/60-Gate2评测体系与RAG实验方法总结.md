# 60 - Gate 2 评测体系与 RAG 实验方法总结

> 面向零基础读者：如何把一个"能跑的 RAG Demo"升级成"可评测、可复现、
> 可解释的 Retrieval 系统"。本文不按任务时间线写，按方法组织。

## 1. 什么是 Benchmark

Benchmark = 一组固定的输入 + 固定的标准答案 + 固定的打分规则。

为什么需要它？

```text
没有 Benchmark：改一个参数后"感觉变好了"，无法判断是真实的还是偶然；
有 Benchmark：同一输入、同一答案、同一规则，任何改动都能量化前后差异。
```

一个可用的 RAG Benchmark 至少要有三个部分：Corpus、Query、Gold。

## 2. Corpus / Query / Gold

```text
Corpus：检索系统能看到的文档集合
  → 冻结：文件清单 + SHA-256 + size，任何文件变化都要被发现

Query：用户会问的问题
  → 本项目 50 条，其中 43 条单文档、7 条多文档

Gold：每条 Query 的标准答案（relevant files）
  → document-level：标记"哪些文档是相关的"
  → 冻结：不得为了让新 Agent 指标变好看而改
```

本项目：

```text
corpus_id         = 870e5864df67（37 份技术文档）
evaluation_set_id = 18c1c0470652（50 case / 58 Gold obligations）
```

## 3. Hit / Recall / MRR / nDCG

Top-5 chunks 检索后按"第一次出现顺序"去重成文档 ranking：

```text
Hit@5：
  Top-5 文档里有没有至少一个 Gold 文档 → 1 / 0

Recall@5：
  检索到的唯一 Gold 文档数 / Gold 文档总数
  （multi-document query 的关键指标）

MRR：
  第一个相关文档排第几 → 1/rank
  （第一名 1.0，第五名 0.2）

nDCG@5：
  文档级 binary relevance + 标准对数折损
  ideal = min(5, |relevant|)
  （同时惩罚"相关但排得靠后"）
```

四个指标回答不同问题：

```text
Hit：有没有找到；
Recall：找到多少（multi-doc 尤其重要）；
MRR：第一个答案多靠前；
nDCG：整体排序质量。
```

## 4. 为什么需要 document-level vs chunk-level

检索单位是 chunk，评测单位是 document：

```text
chunk-level：
  需要知道"哪一段含答案"，需要 chunk-level Gold label
  → 更精确，但标注成本高、目前没有

document-level：
  只要文档被 Top-5 chunk 命中就算相关
  → 能评测系统，但"命中"不等于"命中的 chunk 真有答案"
```

因此本项目所有结论都是 document-level 结论；涉及 chunk 的因果
（例如"某个边界削弱了证据"）只能保持 plausible / unverified。

## 5. ExperimentConfig / experiment_id

一次实验的完整参数（embedding、chunk、retriever、top_k、rrf 等）
构成 `ExperimentConfig`：

```text
experiment_id = stable hash(全部配置字段)
```

任何字段改变 → experiment_id 改变 → 是两个不同实验。

这保证：

```text
同配置重跑 = 同实验身份；
异配置 = 异实验身份，不能混着比较；
chunk_budget_policy 等语义字段必须进身份，否则两个不同行为的
实验会拿到同一个 ID（"实验身份撒谎"）。
```

## 6. Manifest

IndexManifest 是"这次入库到底发生了什么"的不可变快照：

```text
experiment_id
corpus_id
config（= ExperimentConfig.to_dict()）
corpus_entries（文件清单 + SHA-256）
files（每个文件入库结果）
total_chunks / vector_store_count / sparse_index_count
post-index observed facts（aligned：corpus-scoped fingerprint、
actual_content_token_max、actual_model_input_token_max、
actual_would_truncate_count）
```

Manifest 把"配置"和"实际发生"绑定在一起。

## 7. Declared vs Effective Runtime

只相信配置字符串是不够的：

```text
declared：YAML/Config 里写 bm25
effective：Pipeline 实际构造的 retriever 是不是 BM25OnlyRetriever
```

本项目用真实 `isinstance` 校验、从正式模型实例重算 runtime
contract、比对 tokenizer object identity，任何不一致在入库前
fail-fast。

这就是"实验身份不撒谎"的执行层保证。

## 8. Control / Intervention

```text
intervention：你主动改变的那个变量
control：保持不变的对照
```

例子：

```text
想验证"把 chunk budget 换成 BGE-aligned 会怎样"
→ intervention = chunk_budget_policy
→ control = 原 cl100k baseline
```

只改一个变量，其他全部冻结，否则无法归因。

## 9. Ablation

Ablation = 消融 = 去掉/替换一个组件看影响。

```text
Dense-only / BM25-only / Hybrid 对比：
→ 看 fusion 是否值得

Fixed / Recursive 对比：
→ 看 chunk 边界策略是否重要
```

原则：一次只改一个变量；同一策略的三个 retriever 必须共享同一
chunk 配置与 total_chunks。

## 10. Offline vs Formal Experiment

```text
offline / counterfactual：
  用已保存的 channel snapshot 推导"如果只用 Dense 会怎样"
  → 快、零额外运行、适合生成假设

formal experiment：
  ExperimentConfig → experiment_id → 独立 Workspace/Index →
  retrieval → metrics → result
  → 唯一可信的正式事实
```

离线结论必须用正式实验复现（parity validation：宏指标 + 逐 Case
ranking），本项目 Dense/BM25 均为 50/50 exact match、delta=0。

## 11. Correlation vs Causality

```text
相关：aligned 后 would-truncate 变 0，且指标变了
因果：这些变化"就是"截断消失造成的
```

相关不等于因果，因为干预同时改变了 chunk boundaries / overlap /
BM25 统计 / Dense 表示单位。要证明截断因果，需要
"只移除截断、不改变边界"的 intervention 和 chunk-level Gold。

## 12. Negative Result 为什么有价值

如果干预后指标没提升甚至下降（本项目 aligned 后 Dense 下降），
这是有效结果：

```text
它排除"消除截断必然变好"的假设；
它说明影响是 strategy-dependent；
它防止团队继续在错误方向投入。
```

实验的目标是"知道真相"，不是"证明我改对了"。

## 13. Case-Level Error Analysis

只看宏指标会漏掉结构：

```text
宏指标相同，可能 A 赢 5 个、输 5 个；
宏指标上升，可能靠 rescue 掩盖了新 loss。
```

因此要逐 Case 比较：

```text
document ranking 相同/变化数
Hit rescue / loss
Recall improved / worsened
multi-document Recall 单独看
```

本项目 q013/q019/q039/q047（Hybrid Hit 失败）与
q031/q034/q036（multi-doc 不完整）作为 Gate 3 固定 inspection set。

## 14. 为什么不能看一个指标涨了就讲故事

反例：aligned 后 Hybrid Hit 0.92→0.96（涨了）。

但：

```text
MRR/nDCG 反而微降；
Dense 明显下降；
BM25 ranking 36/50 变化但 Gold metrics 稳定；
两个 Hybrid rescue 的 fusion 机制 unresolved。
```

所以必须同时看：

```text
所有指标、Case 分布、control 策略、ranking 变化、因果边界
```

单个指标上升不能支撑"这个改动是好的"。

## 15. 本项目真实例子

### BM25 > Hybrid > Dense

```text
Recursive cl100k（Top-5 document-level）：
  BM25  Hit 0.98 / Recall 0.9533 / nDCG 0.8206
  Hybrid Hit 0.92 / Recall 0.8933 / nDCG 0.7994
  Dense  Hit 0.88 / Recall 0.8633 / nDCG 0.7624
```

限定当前语料；不写"BM25 永远更好"。

### RRF tie

q004 中候选 (2,8) 与 (8,2) 的 RRF 完全同分；Python `set` 顺序跨进程
不稳定 → 排序不确定。修复：

```text
rrf_score DESC → chunk_id ASC
```

并进入实验身份。

### Tokenizer 57/215 truncation

cl100k 说 512，BGE runtime 数出 550；Recursive 215 个 chunk 中
57 个（26.51%）超过 BGE 512 上限，实际会截断。

### Aligned 后 Dense ↓ / Hybrid ↑

```text
aligned（would-truncate 0）：
  Dense  Hit 0.88→0.84
  BM25   Hit 0.98→0.98（ranking 36/50 变）
  Hybrid Hit 0.92→0.96（q039/q047 rescue）
```

结论：intervention 有 strategy-dependent effect；
alignment intervention effect ≠ truncation-only causal effect。

## 16. 面试问答

### Q：RAG 系统为什么要 Benchmark？

因为"感觉回答更好"不可复现、不可比较、不可解释。Benchmark 用固定
Corpus/Query/Gold/规则把改进变成可量化的前后差异，并能暴露
rescue 与 loss 的结构。

### Q：Hit 和 Recall 有什么区别？

Hit 问"有没有找到至少一个"；Recall 问"该找的找到了多少"。
multi-document query 下 Hit=1 但 Recall 可能只有 0.5，所以必须
两个都看。

### Q：experiment_id 有什么用？

它是配置的稳定哈希。保证"同配置=同实验、异配置=异实验"，避免把
不同参数/不同语义的实验混成一个结果，是复现性的身份基础。

### Q：Manifest 为什么不能只有 config？

config 是声明，Manifest 是执行事实：实际入库了多少 chunk、向量库
和 BM25 数量是否一致、corpus-scoped fingerprint 是什么。只有声明
没有事实，实验可以"看起来对"。

### Q：declared vs effective 有什么区别？

declared 是配置里写的，effective 是代码实际执行的。例如配置写
bm25 但 Pipeline 构造出 SimpleRetriever，指标却挂到 bm25 名下——
身份撒谎。所以必须做 runtime binding 校验（类型、contract、
tokenizer 对象）。

### Q：什么是 control？为什么 BM25 是 control？

Control 是保持不变的对照。BM25 不依赖 Dense embedding，但依赖相同
chunk boundaries：如果干预后 BM25 的 Gold metrics 也大幅变化，说明
共同机制在 chunk 层；如果 BM25 稳定（本项目 Hit 0.98→0.98，但
ranking 36/50 变化），说明影响主要在 Dense 依赖路径——但仍不能
直接归因 embedding-input alignment。

### Q：为什么 offline ablation 不能代替正式实验？

Offline 是"如果当初只用这个通道会怎样"的反事实推导，快但只是假设；
正式实验有独立 Workspace/Index/身份/Manifest，是唯一可信事实。
两者必须做 parity 验证。

### Q：相关性能不能当因果？

不能。干预同时改变多个变量（boundaries/overlap/统计单位），
相关只是共同变化；因果需要专门设计（只变一个机制的 intervention）
和更细粒度 Gold。

### Q：负结果有什么用？

负结果排除假设、防止资源浪费、帮助确定边界（例如"消除截断在当前
Benchmark 上没有带来 Dense 提升"）。科学实验的价值在于信息量，
不在于结果方向。

## 书面学习要点

1. Benchmark 三要素：Corpus / Query / Gold，全部冻结且可校验。
2. 四个指标各回答一个问题，multi-document 必须看 Recall。
3. 实验身份（experiment_id）、执行事实（Manifest）、运行行为
   （runtime binding）三层绑定才叫可复现。
4. Control/Intervention、ablation、offline/formal、correlation/
   causality 是实验方法论的基本词汇。
5. 本项目真实结论：BM25 > Hybrid > Dense（当前语料）；chunk
   strategy 有实质影响；Hybrid 失败多为融合层问题；tokenizer
   aligned 干预有 strategy-dependent effect，不等于 truncation
   causal effect。
