# BGE-Aligned Chunk Budget Intervention Contract（G2-DESIGN-19）

> 设计文档，只定义契约，不包含实现代码。
> 前提：G2-DIAG-18/R1/R2/R3 已复审通过；本任务不修改代码、不重跑
> Retrieval 实验。

## 1. 背景事实（已确认）

```text
当前正式 Chunk 预算计数器：TokenCounter → tiktoken cl100k_base
实际 Embedding 运行时：
  SentenceTransformer.max_seq_length = 512
  runtime tokenizer = BertTokenizer
  runtime tokenizer.model_max_length = 512
  num_special_tokens_to_add(pair=False) = 2（当前运行态实测）

would-truncate（Runtime 口径）：
  Recursive：57 / 215 = 26.51%
  Fixed：    71 / 237 = 29.96%
```

下一步要做正式的 tokenizer-aligned chunking intervention，本设计文档
回答"BGE-aligned chunk_size=512 到底意味着什么"以及如何把它做成可
复现、可解释的正式实验。

## 2. 三种预算的定义

必须区分三个概念，不能把
`count(text, add_special_tokens=True)` 同时用于 chunk_size 与 overlap：

```text
model_input_budget
  = SentenceTransformer.max_seq_length
  = 512
  = 包含 [CLS]/[SEP] 等 special tokens 后的最终输入上限

special_token_overhead
  = runtime tokenizer 对单文本实际增加的 special token 数
  = tokenizer.num_special_tokens_to_add(pair=False)
  = 2（当前运行态实测，不是无验证常量；实现时仍须读取）

content_budget
  = model_input_budget - special_token_overhead
  = 512 - 2
  = 510
  = 正文（不含 special tokens）允许的最大 token 数

overlap_content_budget
  = chunk_overlap（正文 token 数）
  = 64（当前冻结值）
  = 不包含 [CLS]/[SEP]
```

约束：

```text
content_tokens(chunk) <= 510
model_input_tokens(chunk) = content_tokens + 2 <= 512
```

因此 BGE-aligned 的 chunk 正文上限是 **510**，而不是 512。

## 3. Chunk 与 Overlap 的不同计数语义

aligned counter 必须概念上区分两个函数：

```text
count_content(text)
  = len(tokenizer(text, add_special_tokens=False, truncation=False)["input_ids"])
  → 用于 chunk boundary 与 overlap 回退

count_model_input(text)
  = len(tokenizer(text, add_special_tokens=True, truncation=False)["input_ids"])
  = count_content(text) + special_token_overhead
  → 用于最终 chunk correctness 验证（<= 512）
```

规则：

- `chunk_size=512` 在 aligned 模式下的正式含义是
  **model input budget**；Chunker 实际使用的切分预算由 counter 推导为
  `content_budget = 512 - special_token_overhead`；
- `chunk_overlap=64` 继续表示**最多 64 个正文 token**，special tokens
  永不进入 overlap 预算；
- 切块/回退只用 `count_content`，避免每块被 [CLS]/[SEP] 污染；
- 每个最终 chunk 再以 `count_model_input(chunk) <= 512` 做后置校验。

## 4. Counter 方案（设计，不实现）

### 4.1 不改现有默认行为

现有 `TokenCounter`（cl100k）保持默认与既有行为不变，所有旧
Baseline 继续依赖它。

### 4.2 新增 EmbeddingRuntimeTokenCounter

新增一个独立 counter（例如 `EmbeddingRuntimeTokenCounter`），包装
实际 SentenceTransformer runtime tokenizer，提供与现有 Chunker
兼容的最小接口：

```text
count(text)             → count_content（不含 special tokens）
count_model_input(text) → 含 special tokens 的最终输入长度
name                    → "embedding_runtime"
model_input_budget      → 512（来自 SentenceTransformer.max_seq_length）
special_token_overhead  → runtime 实测
content_budget          → model_input_budget - overhead
```

统一抽象：如果引入 Protocol/Interface，只定义 Chunker 实际消费的方法
（`count` + 可选 `max_substring` / `substring_start`），不要设计
用不到的宽接口。

### 4.3 事实源原则

继续满足：

```text
原始文本是事实源
Chunk 永远是原文精确子串
tokenizer 只负责预算判断
```

禁止 decode token IDs 后重新构造正文；正文一律从原始字符串的字符
span 切出。

## 5. Runtime Binding

### 5.1 构造绑定

Pipeline 构造 Chunker 时必须把声明好的 counter 注入，而不是让 Chunker
自己 new 一个：

```text
chunk_budget_tokenizer = "embedding_runtime"
→ Pipeline 使用 EmbeddingRuntimeTokenCounter
  （内部从实际 SentenceTransformer 读取 runtime tokenizer）
```

### 5.2 prepare 验证

`_validate_pipeline()` 在正式入库前验证：

```text
实际 Chunker 的 counter.name == ExperimentConfig.chunk_budget_tokenizer
实际 runtime tokenizer class / model_max_length
  == 声明/记录值
实际 SentenceTransformer.max_seq_length == 512（fail-fast）
```

任何不一致 → prepare 立即失败，不得产生正式 index_manifest。

### 5.3 行为指纹绑定

沿用 DIAG-18-R2 的 `runtime_tokenizer_behavior_fingerprint`：

```text
按稳定顺序（strategy → relative_path → chunk_index）
遍历本次实验实际产出的全部 Chunk，
用真正 runtime tokenizer（add_special_tokens=True、truncation=False）
取得 input_ids，流式 SHA-256，取前 16 hex。
```

它作为**运行时完整性事实**记录在 IndexManifest（顶层，不进入
`config`，从而保持 `manifest.config == ExperimentConfig.to_dict()`），
并在 binding/finalize 阶段通过重算校验：

```text
Manifest.runtime_tokenizer_behavior_fingerprint
== 对 Manifest 记录的 chunks 重算值
```

说明：fingerprint 依赖 corpus 与已产出 chunks，属于派生事实，不进
experiment_id；experiment_id 绑定的是可预先声明的运行态契约（见下）。

## 6. Experiment Identity

### 6.1 新字段

ExperimentConfig 新增：

```text
chunk_budget_tokenizer: str
  = "cl100k_base" | "embedding_runtime"
```

要求：strict str、非空、进入 `to_dict()`、自动进入现有 experiment_id
稳定序列化。

建议同时记录（同样进入 config/身份）：

```text
embedding_runtime_max_seq_length = 512
embedding_runtime_tokenizer_class = "BertTokenizer"
```

### 6.2 身份语义

```text
chunk_budget_tokenizer 改变
→ experiment_id 必须改变
```

即使两个实验使用相同 chunk_size/overlap/retriever，只要预算计数器
不同，就是不同实验身份。不得为保持旧 ID 而排除该字段。

### 6.3 旧 Artifact 不变

旧 cl100k Baseline（Dense/BM25/Hybrid 全部实验）保持字节不变，
不补字段、不重写 JSON。新实验使用独立 Workspace / run_id，与旧
实验互不冲突。

## 7. Monotonicity 风险处理（设计决策）

现状：`TokenCounter.max_substring()` / `substring_start()` 的二分
逻辑依赖"token count 随 substring 扩展单调非减"，DIAG-18 已登记为
技术债，且对新的 runtime tokenizer（WordPiece + Lowercase normalizer）
尚未证明成立。

实现 aligned intervention 前必须三选一（本任务不选实现路径，只要求
明确决策条件）：

```text
方案 A：性质验证
  对该 counter + 冻结 Corpus 做系统性质测试，证明在所需搜索语义下
  单调条件成立；不成立则不使用二分。

方案 B：安全边界搜索
  改用不依赖单调假设的搜索（如线性探测/缓存计数），
  用 37 个文件的语料规模换取正确性。

方案 C：post-condition + fail-fast
  保留二分，但每次 max_substring 后验证：
  count(content[start:end]) <= budget，
  且严格模式下 count(content[start:end+1]) > budget；
  违反立即抛错，禁止产出错误 chunk。
```

决策原则：

- 不能假装假设不存在；
- 推荐至少 A/C 组合（性质测试 + 后置验证），具体由实现任务决定；
- 若走 C，二分得到的"看似可行"结果也必须过 post-condition，
  否则 fail-fast。

## 8. 正式干预实验矩阵

下一阶段只做 **Recursive** 三套：

```text
Recursive + Dense  + embedding_runtime
Recursive + BM25   + embedding_runtime
Recursive + Hybrid + embedding_runtime
```

对照：现有 cl100k Recursive 三套正式结果：

```text
Dense  experiment_id = dc220d794578
BM25   experiment_id = dbc497c796d5
Hybrid experiment_id = 3c613202e1ed
```

冻结：corpus_id=870e5864df67、evaluation_set_id=18c1c0470652、
chunk_size=512（model input budget 语义）、chunk_overlap=64、
top_k=5、dense_candidate_k=30、sparse_candidate_k=30、rrf_k=60、
rrf_tie_breaker=chunk_id_asc、embedding=BGE-small-zh-v1.5。

硬校验：

```text
corpus_id / evaluation_set_id / file_count=37 / case_count=50 不变
三套 aligned 的 total_chunks 彼此一致（同一 chunker）
aligned would_truncate 应 = 0（否则 intervention 未成功消除截断）
```

## 9. BM25 为什么必须作为 Control

换 chunk budget tokenizer 会同时改变：

```text
chunk boundaries
total_chunks
overlap 落点
BM25 的 TF / 文档长度统计单位
Dense 的表示单位
Hybrid 的两路候选与 RRF
```

因此如果 aligned 后 Dense/Hybrid 提升，不能自动归因于"仅仅因为不再
截断"。BM25-only 是 control：

```text
若 aligned BM25 也明显变化
→ 说明效果至少部分来自 chunk boundary / 统计单位改变，
  而不只是 Dense 输入不再截断

若 aligned BM25 几乎不变
→ "消除截断 + 边界变化"对 BM25 影响小，
  加强"Dense 侧改善与输入截断相关"的解释
```

## 10. 因果解释等级（预先定义）

```text
Level A：intervention 成功
  aligned 后 would_truncate = 0
  → 确认隐藏截断被消除（只证明这一点）

Level B：检索指标变化
  aligned Dense/Hybrid 提升
  → 支持 "BGE-aligned chunk budget 改善当前 Retrieval"
  → 但 chunk boundaries 同时改变，
    不能严格单独归因于 "仅仅因为没有 truncation"

Level C：因果归因
  需要 BM25 control + Case-level 分析 + 可选 intervention 对比
  （如仅移除截断而不改变边界）才能加强/削弱
```

禁止在只有 Level A+B 证据时宣称 "truncation causally caused all
improvement"。

## 11. 结果解释边界

```text
能说：
  - aligned 配置下 would-truncate = 0
  - aligned 配置下 Dense/BM25/Hybrid 的正式指标（Hit/Recall/MRR/nDCG）
  - 与 cl100k Recursive 对照的 delta 与 Case-level rescue/regression

不能说：
  - "Dense 弱全部由 truncation 导致"
  - "aligned 提升完全来自消除截断"
  - 在 BM25 control 与 Case-level 分析之前做严格因果归因
```

## 12. 回滚 / 兼容旧 Baseline

- 旧 cl100k 是默认路径：不改 `TokenCounter` 默认行为、不改
  `FixedSizeChunker` / `RecursiveChunker` 默认构造；
- aligned 只通过新的 ExperimentConfig 字段显式开启；
- 新实验使用独立 Workspace / run_id，产生新的 experiment_id；
- 回滚 = 不使用新字段，旧 Baseline 与其 Artifact 全部保持字节不变；
- 若 aligned 实验证明不可取，只保留证据，不重写历史。

## 13. 交付物边界

本任务只交付本设计文档。Counter、Chunker 接线、ExperimentConfig
字段、Manifest 字段、正式实验与 59 号学习笔记，均属于后续独立任务。
