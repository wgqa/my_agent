# Chunk Budget vs BGE Tokenizer Alignment Diagnostic（G2-DIAG-18）

> 只读诊断：不修改 Chunker / Embedding / Corpus / Gold，不重新运行
> Retrieval 实验。数据来自冻结 Benchmark Corpus 重新构造的 Chunk
> 与本地 BGE tokenizer 长度统计。

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
- 本项目实测 token 数比值（BGE/cl100k）：
  - Recursive：median 0.9188、p90 1.0452、p95 1.0849、max 1.3398；
  - Fixed：median 0.9199、p90 1.0512、p95 1.0844、max 1.3418。
- 即部分 chunk 在 BGE 下比 cl100k 多出最多约 34% 的 token。

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
- BGE 计数使用
  `AutoTokenizer.from_pretrained("BAAI/bge-small-zh-v1.5",
  local_files_only=True)`，`add_special_tokens=True`、
  `truncation=False`；
- `would_truncate = bge_token_count > 512`；
- `overflow_tokens = max(0, bge_token_count - 512)`；
- 百分位使用固定线性插值方法（与 numpy linear 一致），有测试覆盖；
- 本脚本不调用 Embedding encode / Chroma / BM25 / Retriever /
  ExperimentRunner。

## 5. Recursive 统计（215 Chunks）

```text
cl100k max                        = 512
cl100k over-budget count          = 0（无 Chunker correctness blocker）

BGE token（含特殊 token）：
  min      = 22
  median   = 458.0
  p90      = 526.0
  p95      = 545.3
  p99      = 572.86
  max      = 686

would_truncate count              = 34
would_truncate percentage         = 15.81%
overflow max                      = 174
overflow median（仅超长 chunk）   = 25.5

token ratio（BGE/cl100k）：
  median = 0.91875
  p90    = 1.04524
  p95    = 1.08493
  max    = 1.33984
```

## 6. Fixed 统计（237 Chunks）

```text
cl100k max                        = 512
cl100k over-budget count          = 0（无 Chunker correctness blocker）

BGE token（含特殊 token）：
  min      = 57
  median   = 463.0
  p90      = 530.4
  p95      = 550.4
  p99      = 588.8
  max      = 687

would_truncate count              = 35
would_truncate percentage         = 14.77%
overflow max                      = 175
overflow median（仅超长 chunk）   = 30.0

token ratio（BGE/cl100k）：
  median = 0.91992
  p90    = 1.05117
  p95    = 1.08437
  max    = 1.34180
```

## 7. 是否真实存在 would-truncate Chunk

是，且比例不低：

```text
Recursive：34 / 215 = 15.81%
Fixed：    35 / 237 = 14.77%
```

两套策略的 chunk 边界不同，但超长比例接近，说明这是
"cl100k 预算与 BGE 输入上限不匹配"的系统性工程边界，不是某一策略
特有的偶然现象。

## 8. 严重程度

- 最大 overflow：Recursive 174 / Fixed 175；
- 超长 chunk 的 overflow 中位数：Recursive 25.5 / Fixed 30.0，即
  大多数超长 chunk 只超 25-30 个 token；
- 超过 100 token 的极端超长只有个别 chunk（两策略下都是
  `agent_frameworks/LangChain-LangGraph-02-StateGraph与工具循环.md`
  的 chunk 0：cl100k 512，BGE 686/687）。
- 超长集中在包含代码块、JSON、表格、长列表的中英混排文档。

## 9. 超长 Chunk 集中的文档

Recursive（21 个文件至少 1 个超长 chunk）：

```text
tool_calling/工具设计.md            5
prompt/提示工程基础.md             3
tool_calling/Function-Calling原理.md 3
LangChain-LangGraph-03-Checkpoint   2
finetuning/数据工程.md              2
finetuning/训练与评估.md            2
prompt/提示工程高级技巧.md          2
prompt/评估与优化.md                2
其余 13 个文件各 1
```

Fixed（19 个文件至少 1 个超长 chunk）：

```text
tool_calling/工具设计.md            6
tool_calling/Function-Calling原理.md 4
LangChain-LangGraph-02/03          各 2
deployment/部署架构.md              2
llm/Transformer架构-01             2
mcp/MCP协议-01                     2
prompt/提示工程基础/高级技巧/评估与优化 各 2
其余 9 个文件各 1
```

模式一致：工具设计、Function Calling、Prompt 工程、部署与评估类文档
（代码/JSON/表格密集）是超长高发区。

## 10. 与 7 个重点 Case 的描述性关联

以下只回答"Gold 文件的某些 chunk 是否存在 BGE truncation 风险"，
不回答"该 Case 是否因截断失败"：

```text
q013（llm/预训练.md）
  Recursive：0 个超长 chunk；Fixed：0 个超长 chunk
  → Gold 文件无截断风险，截断不能解释该失败

q019（llm/Transformer架构-03-训练推理与高效Attention.md）
  Recursive：0；Fixed：0
  → Gold 文件无截断风险

q039（rag/检索与生成.md）
  Recursive：1；Fixed：0
  → 仅 Recursive 下该 Gold 文件存在 1 个截断风险 chunk

q047（llm/Transformer架构-04-采样与工程联系.md）
  Recursive：0；Fixed：0
  → Gold 文件无截断风险

q031（rag/文档处理.md, rag/检索与生成.md）
  文档处理.md：0/0；检索与生成.md：Recursive 1 / Fixed 0

q034（rag/高级RAG.md, rag/检索与生成.md）
  高级RAG.md：Recursive 1 / Fixed 1；检索与生成.md：1/0

q036（提示工程高级技巧.md, rag/文档处理.md,
      tool_calling/Function-Calling原理.md）
  提示工程高级技巧.md：2/2；文档处理.md：0/0；
  Function-Calling原理.md：3/4
  → 3 个 Gold 文件中 2 个存在截断风险，其中
    Function-Calling原理.md 风险最高（Recursive 3、Fixed 4）
```

## 11. 当前能够支持的结论

1. **两套 tokenizer 计数不可互换**：BGE/cl100k 比值中位数约 0.92、
   p95 约 1.08、最大约 1.34，长度关系因文本而异；
2. **would-truncate 工程边界真实存在**：两策略均有约 15% 的 chunk
   在 cl100k 预算内但超过 BGE 512 输入上限；
3. **这不是 Chunker correctness blocker**：所有 chunk 的 cl100k
   计数均 ≤ 512，无 oversized chunk；
4. **超长有集中模式**：代码/JSON/表格密集的中英混排文档风险最高；
5. **截断风险不能解释全部重点失败 Case**：q013/q019/q047 的 Gold
   文件没有截断 chunk；q039/q031/q034/q036 的部分 Gold 文件存在
   截断风险 chunk，q036 最突出。

## 12. 当前不能支持的结论

1. **"q036（或 q039 等）就是因截断失败"**：没有 chunk-level Gold
   label，也没有 intervention experiment；
2. **"would-truncate 一定导致实际性能下降"**：BGE 是否在推理时截断、
   截断后是否改变最终表示，需要模型侧实验验证；
3. **"换 TokenCounter 一定会变好"**：换 tokenizer 会同时改变 chunk
   boundaries、total_chunks、overlap、Dense、BM25、Hybrid，属于新的
   正式实验变量，本轮不执行。

## 13. 是否值得下一步调整 Chunk budget tokenizer

证据表明 alignment mismatch 真实存在（约 15% chunk 超 BGE 上限），
值得作为下一组可验证实验假设，但本任务不修改 TokenCounter。

候选假设（只提出）：

```text
H9：把 chunk budget 换成 BGE tokenizer 计数后，
would-truncate 比例会显著下降，但 chunk 边界/总数/检索结果都会改变；
需要通过独立正式实验对比，不能凭本诊断直接判断优劣。
```

## 14. 分析 Artifact 与脚本

- Artifact：[agent_ai_v1_tokenizer_alignment.json](D:\学习\rag实战项目\rag-knowledge-base\docs\experiments\agent_ai_v1_tokenizer_alignment.json)
  （diagnostic_id=b04d2dce47c9，schema_version=1，无绝对路径）；
- 脚本：[analyze_tokenizer_alignment.py](D:\学习\rag实战项目\rag-knowledge-base\scripts\analyze_tokenizer_alignment.py)
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
