# Chunk Budget vs BGE Tokenizer Alignment Diagnostic（G2-DIAG-18）

> 只读诊断：不修改 Chunker / Embedding / Corpus / Gold，不重新运行
> Retrieval 实验。G2-DIAG-18-R1 将长度契约绑定实际
> SentenceTransformer 运行时（非独立 AutoTokenizer）。

## 1. 为什么会有两套 tokenizer

RAG 链路中"token"至少出现在两个不同环节：

```text
Chunk 预算：
TokenCounter → tiktoken cl100k_base
决定一个 chunk 大约占多少预算、何时换块、overlap 回退多少

Embedding 输入：
BAAI/bge-small-zh-v1.5 → BertTokenizer（本地实际为 BertTokenizer）
决定模型真正接收的 token 序列，超过 model_max_length 会发生截断
```

两者由不同组件决定，项目没有约定它们必须一致，因此存在
tokenizer alignment 工程边界。

## 2. cl100k token 与 BGE token 为什么不能互换

cl100k_base（tiktoken，BPE）与 BERT 系 tokenizer（WordPiece/BERT
词表）使用不同分词算法、不同词表：

- 同一个中英混排文本，两套 tokenizer 的 token 数不同；
- 本项目实测 token 数比值（Runtime BGE/cl100k，R1 口径）：
  - Recursive：median 0.9685、p90 1.0927、p95 1.1407、max 1.3809；
  - Fixed：median 0.9691、p90 1.0943、p95 1.1444、max 1.3828。
- 即部分 chunk 在 BGE 下比 cl100k 多出最多约 38% 的 token。

注意：BGE 计数包含特殊 token（[CLS]/[SEP]），因此该比值不是严格的
"纯 tokenizer 压缩率"定义，只用于直观展示两套 tokenizer 的长度差异。

## 3. 512 的两种含义

```text
chunk_size = 512
含义一：≤ 512 个 TokenCounter / cl100k_base token（chunk 预算）
含义二：BGE 模型 max_seq_length = 512（Embedding 输入上限，
        包含特殊 token 后的最终输入长度）
```

两者相等只是巧合般的配置选择，不代表两套 tokenizer 一一对应。
本诊断从本地 tokenizer 配置读取 `model_max_length = 512`（不是把
512 当作固定事实）。

## 4. 诊断方法与硬校验

- Corpus：`02_corpus_candidate`（37 个 .md，corpus_id=870e5864df67）；
- 使用项目正式 `FixedSizeChunker(512, 64)` 与 `RecursiveChunker(512, 64)`
  逐文件重建 Chunk；
- 硬校验：Recursive == 215、Fixed == 237，与正式实验完全一致；
- cl100k 计数使用项目真实 `TokenCounter()`（实际 name=cl100k_base）；
- BGE 计数使用 **实际 SentenceTransformer 运行时的 tokenizer**
  （G2-DIAG-18-R1）：
  ```text
  SentenceTransformer("BAAI/bge-small-zh-v1.5", local_files_only=True)
  → model.max_seq_length（正式 encode 路径的截断上限）
  → model[0].tokenizer（真正执行 encode 的 tokenizer）
  ```
  `add_special_tokens=True`、`truncation=False` 计算未截断长度；
- 运行时验证：`SentenceTransformer.max_seq_length == 512`，
  必须与预期 512 一致（否则 fail-fast）；runtime tokenizer
  `model_max_length` 只作为运行态事实记录，不要求与 effective max
  相同（G2-DIAG-18-R2 契约）；
  `effective_embedding_max_seq_length = 512`；
- `would_truncate = bge_token_count > effective_embedding_max_seq_length`；
- `overflow_tokens = max(0, bge_token_count - effective_max)`；
- R2 新增 `runtime_tokenizer_behavior_fingerprint`：按稳定顺序
  （strategy → relative_path → chunk_index）遍历全部冻结 Chunk，
  使用真正 runtime tokenizer（add_special_tokens=True、
  truncation=False）取得 input_ids，流式写入 SHA-256，取前 16 位
  hex；Artifact 只保存 fingerprint，不保存 input_ids；
- 百分位使用固定线性插值方法（与 numpy linear 一致），有测试覆盖；
- 本脚本不调用 `SentenceTransformer.encode()` / Chroma / BM25 /
  Retriever / ExperimentRunner。

### R1 与主体诊断的数字差异及原因

R0（主体诊断）使用独立 `AutoTokenizer.from_pretrained(...)`，当时
Recursive 34 / Fixed 35 个 would-truncate（R0 / standalone
AutoTokenizer 历史诊断结果）。R1 改用实际运行时 tokenizer 后为
Recursive 57 / Fixed 71。原因：

```text
sentence-transformers 加载 BGE 时修改了 tokenizer 的 normalizer：
Sequence([Lowercase(), BertNormalizer(clean_text=True,
handle_chinese_chars=True, strip_accents=None, lowercase=False)])
```

即运行时 tokenizer 额外启用了 Lowercase 归一化，独立 AutoTokenizer
没有；英文/代码中的大小写 token 在运行时被小写化后重新切分，token 数
不同（实测同一字符串 `"import React from 'react'"`：standalone 10
tokens、runtime 11 tokens）。因此主体诊断低估了实际 Embedding 路径的
输入长度，R1 统计以运行时契约为准，如实保存并解释差异。

### R2：tokenizer class ≠ tokenizer behavioral identity

R1 提供了一个真实反例：

```text
Tokenizer A（独立 AutoTokenizer）：
  class = BertTokenizer
  model_max_length = 512

Tokenizer B（SentenceTransformer runtime）：
  class = BertTokenizer
  model_max_length = 512

但实际 tokenization output 不同
→ would-truncate 34/35 vs 57/71
```

因此 class name 与 model_max_length 不足以定义 tokenizer identity。
真正影响模型输入的行为因素还包括：

```text
normalizer（本例：runtime 多一个 Lowercase）
pre-tokenizer
vocabulary mapping
special-token handling
runtime wrapper/config
```

R2 使用 `runtime_tokenizer_behavior_fingerprint`（基于当前冻结
Corpus 上实际 input_ids 的 SHA-256）作为
corpus-scoped tokenizer behavior fingerprint，并进入 diagnostic_id。
它能保证：在当前冻结 Benchmark 输入上，tokenization output 改变
→ fingerprint 改变 → diagnostic_id 改变；但它不是对 tokenizer 在
所有可能输入上的数学完整描述。因此：

```text
同 class + 同 max + 行为不同
→ fingerprint 不同 → diagnostic_id 不同
```

身份历史：

```text
R1 diagnostic_id = 51e18bf2cff6
R2 diagnostic_id = 801dda0b7ca0（绑定 behavior fingerprint）
```

R1 的历史解释与数字保留在上文，不覆盖。

## 5. Recursive 统计（215 Chunks）

```text
cl100k max                        = 512
cl100k over-budget count          = 0（无 Chunker correctness blocker）

Runtime BGE token（含特殊 token）：
  min      = 22
  median   = 484.0
  p90      = 551.6
  p95      = 565.9
  p99      = 617.94
  max      = 707

would_truncate count              = 57
would_truncate percentage         = 26.51%
overflow max                      = 195
overflow median（仅超长 chunk）   = 32.0

token ratio（Runtime BGE/cl100k）：
  median = 0.96853
  p90    = 1.09270
  p95    = 1.14069
  max    = 1.38086
```

## 6. Fixed 统计（237 Chunks）

```text
cl100k max                        = 512
cl100k over-budget count          = 0（无 Chunker correctness blocker）

Runtime BGE token（含特殊 token）：
  min      = 58
  median   = 489.0
  p90      = 551.4
  p95      = 569.6
  p99      = 617.4
  max      = 708

would_truncate count              = 71
would_truncate percentage         = 29.96%
overflow max                      = 196
overflow median（仅超长 chunk）   = 28.0

token ratio（Runtime BGE/cl100k）：
  median = 0.96914
  p90    = 1.09435
  p95    = 1.14436
  max    = 1.38281
```

## 7. 是否真实存在 would-truncate Chunk

是，且比例不低：

```text
Recursive：57 / 215 = 26.51%（运行时口径）
Fixed：    71 / 237 = 29.96%（运行时口径）
```

两套策略的 chunk 边界不同，但超长比例都在 1/4 以上，说明这是
"cl100k 预算与 BGE 输入上限不匹配"的系统性工程边界，不是某一策略
特有的偶然现象。R0 / standalone AutoTokenizer 历史诊断结果为
34/215 与 35/237（仅历史口径，不是当前结果），低估了实际运行时
输入长度，详见第 4 节差异说明。

## 8. 严重程度

- 最大 overflow：Recursive 195 / Fixed 196；
- 超长 chunk 的 overflow 中位数：Recursive 32.0 / Fixed 28.0，即
  大多数超长 chunk 只超 28-32 个 token；
- 超过 100 token 的极端超长：Recursive 3 个、Fixed 4 个；最大的是
  `agent_frameworks/LangChain-LangGraph-02-StateGraph与工具循环.md`
  chunk 0（cl100k 512，Runtime BGE 707/708，overflow 195/196），
  Fixed 下 `tool_calling/Function-Calling原理.md` chunk 2 达 184。
- 超长集中在包含代码块、JSON、表格、长列表的中英混排文档。

## 9. 超长 Chunk 集中的文档

Recursive（28 个文件至少 1 个超长 chunk）：

```text
tool_calling/工具设计.md            5
prompt/提示工程基础.md             4
tool_calling/Function-Calling原理.md 4
finetuning/数据工程.md              3
finetuning/训练与评估.md            3
llm/Transformer架构-01             3
prompt/提示工程高级技巧.md          3
prompt/评估与优化.md                3
vector_db/核心概念.md               3
其余 20 个文件各 1-2
```

Fixed（32 个文件至少 1 个超长 chunk）：

```text
tool_calling/工具设计.md            6
rag/高级RAG.md                      5
tool_calling/Function-Calling原理.md 5
deployment/推理框架.md              3
deployment/部署架构.md              3
finetuning/训练与评估.md            3
llm/Transformer架构-01             3
prompt/提示工程基础/高级技巧/评估与优化 各 3
vector_db/核心概念.md               3
其余 24 个文件各 1-2
```

模式一致：工具设计、Function Calling、Prompt 工程、部署与评估类文档
（代码/JSON/表格密集）是超长高发区；R1 运行时口径下覆盖文件更广
（Recursive 28 / Fixed 32 个文件）。

## 10. 与 7 个重点 Case 的描述性关联

以下只回答"Gold 文件的某些 chunk 是否存在 BGE truncation 风险"，
不回答"该 Case 是否因截断失败"：

```text
q013（llm/预训练.md）
  Recursive：1 个超长 chunk；Fixed：1 个超长 chunk

q019（llm/Transformer架构-03-训练推理与高效Attention.md）
  Recursive：1；Fixed：1

q039（rag/检索与生成.md）
  Recursive：1；Fixed：1

q047（llm/Transformer架构-04-采样与工程联系.md）
  Recursive：2；Fixed：2

q031（rag/文档处理.md, rag/检索与生成.md）
  文档处理.md：Recursive 2 / Fixed 2；检索与生成.md：1/1

q034（rag/高级RAG.md, rag/检索与生成.md）
  高级RAG.md：Recursive 2 / Fixed 5；检索与生成.md：1/1

q036（提示工程高级技巧.md, rag/文档处理.md,
      tool_calling/Function-Calling原理.md）
  提示工程高级技巧.md：3/3；文档处理.md：2/2；
  Function-Calling原理.md：4/5
  → 3 个 Gold 文件全部存在截断风险，
    Function-Calling原理.md 风险最高（Recursive 4、Fixed 5）
```

## 11. 当前能够支持的结论

1. **两套 tokenizer 计数不可互换**：Runtime BGE/cl100k 比值中位数约
   0.97、p95 约 1.14、最大约 1.38，长度关系因文本而异；
2. **would-truncate 工程边界真实存在**：两策略分别有 26.51% /
   29.96% 的 chunk 在 cl100k 预算内但超过 effective runtime max
   （512）；
3. **这不是 Chunker correctness blocker**：所有 chunk 的 cl100k
   计数均 ≤ 512，无 oversized chunk；
4. **超长有集中模式**：代码/JSON/表格密集的中英混排文档风险最高；
5. **Level 1（tokenizer length mismatch）已直接证明**：cl100k count
   ≠ BGE count，且不能互换；
6. **Level 2（actual runtime truncation）已确认**：
   `SentenceTransformer.max_seq_length = 512`，其属性文档明确
   "Longer inputs will be truncated"；当前超 512 的 chunk 就是正式
   BGEEmbedding.encode 路径实际会发生输入截断的 chunk。7 个重点 Case
   的 Gold 文件现在全部存在 1-5 个截断风险 chunk，q036 最突出。

## 12. 当前不能支持的结论

1. **"q036（或 q039 等）就是因截断失败"**：没有 chunk-level Gold
   label，也没有 intervention experiment（Level 3 causality 仍
   currently unverified）；
2. **"would-truncate 一定导致实际性能下降"**：即使确认会发生截断，
   截断是否影响最终向量/检索结果，仍需 intervention 实验验证；
3. **"换 TokenCounter 一定会变好"**：换 tokenizer 会同时改变 chunk
   boundaries、total_chunks、overlap、Dense、BM25、Hybrid，属于新的
   正式实验变量，本轮不执行。

## 13. 是否值得下一步调整 Chunk budget tokenizer

证据表明 alignment mismatch 真实存在：按实际 SentenceTransformer
runtime tokenizer 口径，Recursive 57/215 ≈ 26.5%、Fixed 71/237 ≈
30.0% 的 Chunk 超过 effective max_seq_length=512。这值得作为下一组
可验证实验假设，但本任务不修改 TokenCounter。

候选假设（只提出）：

```text
H9：把 chunk budget 换成 BGE tokenizer 计数后，
would-truncate 比例会显著下降，但 chunk 边界/总数/检索结果都会改变；
需要通过独立正式实验对比，不能凭本诊断直接判断优劣。
```

## 14. 分析 Artifact 与脚本

- Artifact：[agent_ai_v1_tokenizer_alignment.json](./agent_ai_v1_tokenizer_alignment.json)
  （diagnostic_id=801dda0b7ca0，schema_version=1，无绝对路径；
  R2 起绑定 runtime tokenizer、effective max 与
  runtime_tokenizer_behavior_fingerprint=1b865a1b28144ede；
  R1 历史 identity=51e18bf2cff6）；
- 脚本：[analyze_tokenizer_alignment.py](../../scripts/analyze_tokenizer_alignment.py)
  （只读，不调用 Embedding/VectorStore/BM25/Retriever/Runner）；
- 百分位方法：线性插值（与 numpy.percentile linear 一致），测试覆盖。

## 15. 顺手登记的技术债

`TokenCounter.max_substring()` / `substring_start()` 的二分逻辑注释
假设 "BPE 编码长度随字符串增长单调非减"：

```text
BPE token-count monotonicity assumption 需要单独验证。
```

本任务不修改该算法，也不把它与 tokenizer alignment 混成同一个修复；
后续由单独任务决定是否需要性质测试或算法调整。
