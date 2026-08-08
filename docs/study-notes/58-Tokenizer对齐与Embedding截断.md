# 58 - Tokenizer 对齐与 Embedding 截断

> 面向项目作者的学习笔记，配合 G2-DIAG-18 阅读。
> 目标：讲清"为什么 chunk 预算里的 512 和 Embedding 模型的 512
> 不是一回事"，以及这种不一致可能带来什么工程后果。

## 1. tokenizer 是什么

Tokenizer 把文本变成模型能处理的整数序列（token ids）。模型不直接
"读字"，而是读 token：

```text
"你好 world" → tokenizer → [101, 233, 190, 12, 456, 102]
```

不同模型使用不同的 tokenizer，即使面对同一段文本，token 数量也可能
不同。

## 2. 为什么不同模型 tokenizer 不一样

Tokenizer 是模型训练时一起定下来的组件，跟模型绑定：

- 词表不同（谁认识哪些词/子词）；
- 分词算法不同；
- 特殊 token 不同（[CLS]/[SEP]/<s>/</s>...）。

所以"token 数"永远要问一句：**这是谁的 tokenizer 数出来的？**

## 3. BPE / tiktoken 与 BERT tokenizer 的基本区别

### BPE（Byte-Pair Encoding）

先从字符/字节开始，反复合并最常见的相邻对，形成子词词表。

- tiktoken `cl100k_base` 就是 BPE 类编码，词表约 10 万；
- 常见做法是先把文本编码成 UTF-8 字节，再在字节序列上做 BPE，
  因此能处理任意 Unicode，包括中文、Emoji。

### BERT 系 tokenizer（本项目 BertTokenizer，WordPiece）

- 先按空格/标点切分单词，再把单词进一步切成子词（## 前缀表示
  子词续接）；
- 中文通常按字切（BERT 中文词表里每个常用字是一个 token）；
- 有 [CLS]、[SEP]、[PAD]、[UNK]、[MASK] 等特殊 token。

结论：两者算法、词表、特殊 token 都不同，token 数不能互换。

## 4. 为什么"512 token"不是通用长度单位

"512 token"必须带定语：

```text
512 个 cl100k_base token（chunk 预算）
≠ 512 个 BERT/BGE token（Embedding 输入）
```

同一个 chunk，用 cl100k 数可能是 512，用 BGE tokenizer 数可能是
550 甚至 680。本项目实测中，两套计数比值最大到约 1.34，也就是同一
文本在 BGE 下多出约 34% 的 token。

## 5. special tokens 为什么占模型长度

BERT 类模型的输入通常以 [CLS] 开头、[SEP] 结尾：

```text
[CLS] token1 token2 ... tokenN [SEP]
```

这些特殊 token 也计入输入长度。判断是否超过
`max_seq_length=512` 时，必须用 `add_special_tokens=True` 之后的
最终长度，而不是只看正文 token 数。

本项目统计中：

```text
bge_token_count = len(input_ids)  # 包含 [CLS]/[SEP]
```

## 6. truncation 是什么

Truncation 是"输入超过模型最大长度时，把多余部分丢掉"：

- 默认策略通常保留开头（或开头+结尾）；
- 被丢掉的部分模型完全看不到；
- 如果答案证据恰好落在被截断的部分，检索质量/生成质量都会受影响。

判断一个 chunk 是否会被截断：

```text
would_truncate = bge_token_count > max_seq_length
overflow_tokens = max(0, bge_token_count - max_seq_length)
```

## 7. SentenceTransformer / BGE 超长输入会发生什么

BGE-small-zh-v1.5 通过 SentenceTransformer 加载，底层 BERT tokenizer
的 `model_max_length = 512`。输入超过 512 时，编码器/数据整理器会按
设置截断（本项目是 `truncation=False` 统计"本会被截断"的长度，不真的
截断）。

实际后果：

```text
超过 512 的 chunk：
→ 输入被截断到 512
→ 尾部内容不进模型
→ 最终向量只反映前 512 token 的信息
→ 尾部若有 Query 需要的证据，就检索不到
```

注意区分两层：

```text
Level 2（是否实际发生截断）：confirmed。
当前正式运行时 SentenceTransformer.max_seq_length = 512，
输入 >512 的 chunk 在正式 BGEEmbedding / SentenceTransformer
路径会发生输入截断。

Level 3（截断是否删除 Query 所需关键证据、是否导致 Retrieval
failure）：currently unverified。
取决于具体证据位置与后续 intervention 实验。
```

## 8. 为什么 Chunker tokenizer 与 Embedding tokenizer 不一致可能产生隐藏截断

Chunker 按自己的预算切 chunk：

```text
TokenCounter 说：这段文本 = 512 cl100k token，OK，不出块
```

但 Embedding 端：

```text
同一段文本 = 550 BGE token > 512
→ 入模型时会被截断
```

于是出现"Chunker 认为完全合规、Embedding 实际吃不下"的隐藏截断。
它不会报错（除非模型侧抛索引错误），所以是静默的工程边界。

本项目 G2-DIAG-18 实测：

```text
Recursive：57 / 215 = 26.51% chunk 会截断（R1 运行时口径）
Fixed：    71 / 237 = 29.96% chunk 会截断（R1 运行时口径）
```

注：R0（主体诊断）用独立 AutoTokenizer 得到 34/35
（R0 / standalone 历史口径），R1 改为实际 SentenceTransformer
运行时的 tokenizer 后为 57/71（原因见 12.1）。

## 9. 为什么不能发现问题后直接换 tokenizer

直觉："既然 BGE 超长，那把 TokenCounter 换成 BGE tokenizer 不就好了？"

但换 tokenizer 不是换一个计数器那么简单：

```text
新的 token 计数 → 新的切分位置
→ chunk boundaries 全部改变
→ total_chunks 改变
→ overlap 语义改变
→ Dense 表示单位改变
→ BM25 统计单位改变
→ Hybrid/RRF 候选改变
```

这是一次全新的实验配置，不是"修正同一个实验"。

## 10. 换 tokenizer 为什么等于改变实验变量

可复现实验的身份由配置决定：

```text
ExperimentConfig 里记录 chunk_strategy / chunk_size / chunk_overlap /
embedding_model ...
```

如果悄悄把 chunk 计数从 cl100k 换成 BGE tokenizer，但 ExperimentConfig
看起来没变，就会得到"同一身份、不同行为"的假复现。

正确做法是：先登记证据（本诊断），再把它作为新的实验变量，进入
ExperimentConfig 与 experiment_id，用正式实验对比。

## 11. 如何设计公平的 tokenizer-alignment 实验

如果后续要做：

```text
变量：chunk budget tokenizer（cl100k_base → BGE BertTokenizer）
冻结：Corpus / Gold / Query / chunk_size / overlap / Embedding /
      Retriever / top_k / candidate_k / rrf_k
```

并：

- 把 tokenizer 身份写进 ExperimentConfig（不能只是代码内部替换）；
- 记录新的 experiment_id；
- 硬校验 total_chunks 与 Manifest 一致；
- 先做 would-truncate 比例对比，再做 Retrieval 指标对比；
- 同时检查是否有 chunk 在 BGE 下超过 512 但 cl100k 未超
  （alignment 改善的量化指标）。

## 12. 本项目真实统计结果

```text
Recursive（215 chunks，R1 运行时口径）：
  cl100k max = 512（无 over-budget）
  Runtime BGE: median 484 / p90 551.6 / p95 565.9 / p99 617.94 / max 707
  would-truncate: 57（26.51%）
  overflow: max 195 / 超长中位数 32.0

Fixed（237 chunks，R1 运行时口径）：
  cl100k max = 512（无 over-budget）
  Runtime BGE: median 489 / p90 551.4 / p95 569.6 / p99 617.4 / max 708
  would-truncate: 71（29.96%）
  overflow: max 196 / 超长中位数 28.0
```

Runtime 契约：`SentenceTransformer.max_seq_length = 512`、
runtime tokenizer `model_max_length = 512`、类型 BertTokenizer。
重点 Case 的描述性关联（R1 口径，每个数字为 Recursive / Fixed 的超长
chunk 数）：

```text
q013（预训练.md）：1 / 1
q019（Transformer架构-03）：1 / 1
q039（检索与生成.md）：1 / 1
q047（Transformer架构-04）：2 / 2
q031：文档处理.md 2/2、检索与生成.md 1/1
q034：高级RAG.md 2/5、检索与生成.md 1/1
q036：提示工程高级技巧.md 3/3、文档处理.md 2/2、
      Function-Calling原理.md 4/5
```

只能说明"存在截断风险"，不能证明"某个 Case 就是截断导致失败"。

### 12.1 tokenizer.model_max_length vs SentenceTransformer.max_seq_length

这是 G2-DIAG-18-R1 最重要的新增知识点。

#### 两个概念

```text
tokenizer.model_max_length：
transformers tokenizer 自己的属性，表示"这个 tokenizer 认为
模型最多能接受多长输入"。

SentenceTransformer.max_seq_length：
真正执行 Embedding 的 SentenceTransformer 暴露的输入长度上限，
来自其第一个 Transformer module；超过该值的输入会被截断。
```

在本项目中两者最终都是 512：

```text
模型加载时 tokenizer.model_max_length 会被
min(tokenizer.model_max_length, config.max_position_embeddings)
封顶；
SentenceTransformer.max_seq_length 直接读取该值。
```

#### 为什么两者可能不同

理论上存在不一致场景：

- SentenceTransformer 的 module 配置可以单独设置
  `max_seq_length`（训练/推理脚本可以覆盖）；
- tokenizer 的 `model_max_length` 只反映 tokenizer 侧配置；
- 真正截断发生在 SentenceTransformer encode 的数据整理阶段，
  以 `SentenceTransformer.max_seq_length` 为准。

#### 为什么只检查 tokenizer.model_max_length 还不够

面试核心答案：

```text
真正执行 Embedding 的是 SentenceTransformer；
实验必须绑定 effective runtime contract，
而不能只验证某个底层配置文件看起来是什么。
```

这和之前"declared config vs effective runtime behavior"是同一思想：

```text
ExperimentConfig 写 bm25 但实际 Retriever 是 SimpleRetriever
→ 实验身份撒谎；

诊断只读 AutoTokenizer.model_max_length 但实际 encode 用
SentenceTransformer 的 tokenizer/max_seq_length
→ 诊断事实可能撒谎。
```

#### 本项目 R1 的实际发现

独立 `AutoTokenizer.from_pretrained("BAAI/bge-small-zh-v1.5")` 与
实际 `SentenceTransformer(...)[0].tokenizer` 都是 BertTokenizer、
`model_max_length=512`，但 token 计数不同：

```text
sentence-transformers 给 runtime tokenizer 增加了
Lowercase() normalizer：
Sequence([Lowercase(), BertNormalizer(...)])
```

实测 `"import React from 'react'"`：standalone 10 tokens、
runtime 11 tokens。因此 would-truncate 从 34/35 变为 57/71，
说明"同一个模型名"下独立 AutoTokenizer 可能低估实际输入长度。

### 12.2 Tokenizer identity 到底是什么？

这是 G2-DIAG-18-R2 的重点：**tokenizer identity 不能只由模型名、
class 或 max length 定义**。

#### 哪些信息不足以定义 identity

```text
模型名（"BAAI/bge-small-zh-v1.5"）：
  同一个模型名可能被不同 wrapper 加载出不同 tokenizer 行为。

Tokenizer class（"BertTokenizer"）：
  只是实现类型，不代表具体配置。

model_max_length（512）：
  只描述长度上限，不描述如何把文本变成 token。
```

#### 真正影响行为的因素

```text
normalizer（clean_text / handle_chinese_chars / lowercase / strip_accents）
pre-tokenizer（按空格/标点预切分规则）
vocabulary（词表与 id 映射）
special-token handling（[CLS]/[SEP] 是否/如何添加）
runtime wrapper / config（SentenceTransformer 对 tokenizer 的修改）
```

#### 本项目真实反例

```text
Tokenizer A：独立 AutoTokenizer
  class = BertTokenizer、model_max_length = 512

Tokenizer B：SentenceTransformer runtime tokenizer
  class = BertTokenizer、model_max_length = 512

但 B 多了 Lowercase normalizer
→ 同一文本 token ids / counts 不同
→ would-truncate 34/35 vs 57/71
```

因此：

```text
class name ≠ tokenizer behavioral identity
```

#### 本项目最终做法

R2 引入 `runtime_tokenizer_behavior_fingerprint`：

```text
按稳定顺序（strategy → relative_path → chunk_index）
遍历全部冻结诊断 Chunk；
用真正 runtime tokenizer（add_special_tokens=True、truncation=False）
取得 input_ids；
把 (strategy, relative_path, chunk_index, input_ids) 流式写入
SHA-256，取前 16 位 hex。
```

它绑定：

```text
normalizer
pre-tokenization
vocabulary mapping
special-token 行为
当前 Corpus 上实际 tokenization output
```

并进入 diagnostic_id：

```text
同 class + 同 max + 行为不同
→ fingerprint 不同 → diagnostic_id 不同
```

R1 diagnostic_id=51e18bf2cff6，R2 diagnostic_id=801dda0b7ca0
（R1 解释保留，不覆盖）。

注意：`runtime_tokenizer_behavior_fingerprint` 是
corpus-scoped fingerprint——它只保证在当前冻结 Benchmark 输入上，
tokenization output 改变 → fingerprint 改变 → diagnostic_id 改变；
它不是对 tokenizer 在所有可能输入上的数学完整描述。

## 13. 面试追问

### Q1：Tokenizer 是模型的一部分吗？

是。分词算法、词表、特殊 token 在预训练时确定，推理时必须使用同一
tokenizer；换 tokenizer 等于换模型输入口径。

### Q2：BPE 和 BERT tokenizer 有什么区别？

BPE 从字节/字符反复合并高频相邻对形成子词；BERT 系通常先按词/字
切分再切子词（WordPiece 风格）。中文场景 BERT 常按字切，BPE 则按
字节合并。两者词表与 token 数不可互换。

### Q3：为什么 chunk_size=512 不代表 BGE 输入一定 ≤512？

因为 512 是 cl100k token 预算，不是 BGE token。同一文本在两套
tokenizer 下长度不同；BGE 计数还包含 [CLS]/[SEP]。

### Q4：special tokens 会影响截断判断吗？

会。判断是否超 `max_seq_length` 必须用 `add_special_tokens=True`
的最终输入长度；正文 511 个 token + 2 个特殊 token 就已经是 513，
会触发截断判断。

### Q5：超长输入一定会让检索变差吗？

Level 2 与 Level 3 要分开：

```text
Level 2（实际发生截断）：confirmed。
SentenceTransformer.max_seq_length = 512，
输入 >512 的 chunk 在正式 encode 路径会被截断。

Level 3（截断是否造成检索变差）：currently unverified。
要看被截断的部分是否包含证据、截断后剩余内容是否仍足以表征该
chunk，以及 intervention experiment 结果。
```

所以不能说"超长一定变差"，也不能把"是否发生截断"与"截断是否造成
性能下降"写成同一个不确定问题。

### Q6：既然有 26.5%/30% chunk 超长，为什么不能直接换 tokenizer？

因为换 tokenizer 会改变所有 chunk boundaries 和下游检索统计单位，
是新的实验变量，必须通过正式实验 + 新 experiment_id 验证，不能当作
"修 bug"。

### Q6.5：为什么只检查 tokenizer.model_max_length 还不够？

因为真正执行 Embedding 的是 SentenceTransformer，截断发生在它的
encode 数据整理阶段，以 `SentenceTransformer.max_seq_length` 为有效
上限。即使底层 tokenizer 属性看起来正确，运行时可能还有额外配置
（例如本项目 sentence-transformers 给 tokenizer 加了 Lowercase
normalizer，导致 token 数与独立 AutoTokenizer 不同）。所以诊断/实验
必须绑定 effective runtime contract，而不是只读某个底层配置文件。

### Q6.6：tokenizer identity 到底是什么？

不只是模型名、class 或 max length。真正决定模型输入的是实际
tokenization 行为：normalizer、pre-tokenizer、vocabulary、
special-token handling、runtime wrapper/config。最可靠的做法是绑定
"实际 tokenization output 的稳定指纹"（例如本项目的
`runtime_tokenizer_behavior_fingerprint`），而不是只比较类名和属性。

### Q7：如何证明一个失败是截断导致的？

需要：

- chunk-level Gold label（知道证据在哪个 chunk 的哪个位置）；
- 或者 intervention experiment（把该 chunk 截断 vs 不截断对比）；
- 单凭"该文件有超长 chunk + Case 失败"只是相关性。

### Q8：怎样衡量 tokenizer 对齐程度？

常用指标：

```text
would-truncate 比例
overflow_tokens 分布
同一文本两套 tokenizer 的 token 数比值（BGE/cl100k）
```

本项目分别统计了 min/median/p90/p95/p99/max 与超长 chunk 列表。

## 书面学习要点

1. "512 token"必须带 tokenizer 定语；cl100k 预算与 BGE 输入上限不是
   同一把尺子。
2. 判断截断要用包含特殊 token 的最终输入长度。
3. 本 Benchmark 按实际 SentenceTransformer 运行时口径，约 26.5%
   （Recursive）/ 30%（Fixed）的 chunk 存在 would-truncate 风险，
   集中在中英混排 + 代码/JSON/表格密集文档，最大溢出约 195-196
   token；独立 AutoTokenizer 会低估（R0 历史口径 34/35），必须以
   运行时契约为准。
4. 风险 ≠ 因果：没有 chunk-level Gold 与 intervention 前，不能断言
   "q036 就是截断失败"。
5. 换 chunk budget tokenizer 等于换实验变量，必须进入实验身份并做
   正式对比，不能当修复直接改。
6. 检查长度契约要绑定 effective runtime（SentenceTransformer 的
   max_seq_length 与它真正使用的 tokenizer），不能只读底层
   tokenizer 配置。

> 本次 50 Case Benchmark 能支持"当前配置存在约 26.5%-30% 截断风险"这个
> 工程观察，但不能单独证明"截断是当前检索失败的主要原因"。
