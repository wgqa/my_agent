# agent_ai_v1 第一次真实 Baseline Retrieval Error Analysis（G2-ANALYSIS-12）

> 2026-08-08
> 本报告只分析已冻结的 embedding-bound Baseline，不重新运行实验、
> 不调参、不修改 Corpus/Gold/Retriever。

## 0. 分析边界与证据限制

分析只基于以下只读事实来源：

- `index_manifest.json`
- `retrieval_results.json`
- `retrieval_metrics.json`
- `result.json`
- Benchmark Corpus（只读，用于查看文档标题/首段）
- `04_gold/evaluation.jsonl`（只读，用于核对查询与 Gold）

**关键证据限制**：当前 `retrieval_results.json` 只保存最终 Top-K Hit 的
`dense_rank` / `sparse_rank`，没有保存完整 top-30 channel candidate
snapshot。因此，当 Gold 文件没有进入最终 Top-5 时，本报告**不能**声称
“Gold 在 Dense 第 X”或“BM25 根本没召回 Gold”。所有涉及通道候选的
结论统一标注为：

> 现有 Artifact 无法判断，需要后续 channel-level diagnostic / ablation。

本报告只做事实分类，不为填满报告而猜测。

## 1. Baseline 身份与配置

| 项目 | 值 |
|------|-----|
| experiment_id | `874b61d0b5d1` |
| corpus_id | `870e5864df67` |
| evaluation_set_id | `18c1c0470652` |
| retrieval_run_id | `9a4a52cd9319` |
| metrics_run_id | `6706bcfbde7a` |
| result_id | `325d94294803` |
| chunk_strategy | recursive |
| chunk_size / overlap | 512 / 64 |
| retriever_strategy | hybrid |
| top_k | 5 |
| dense_candidate_k / sparse_candidate_k | 30 / 30 |
| rrf_k | 60.0 |
| embedding_provider | bge |
| embedding_model | BAAI/bge-small-zh-v1.5 |
| file_count | 37 |
| total_chunks | 215 |
| case_count | 50 |

## 2. 总体指标

| 指标 | 值 |
|------|-----|
| Hit@5 | 0.92 |
| Recall@5 | 0.8933333333333333 |
| MRR | 0.7866666666666667 |
| nDCG@5 | 0.7993602602248043 |

## 3. 50 Case 指标分布

### Hit@5

| Hit@5 | Case 数 |
|-------|--------|
| 1.0 | 46 |
| 0.0 | 4 |

### Recall@5

| Recall@5 | Case 数 |
|----------|--------|
| 1.0 | 43 |
| [0.5, 1.0) | 3 |
| 0.0 | 4 |

### MRR / nDCG@5 / first_relevant_rank

| 分布项 | 值 |
|--------|-----|
| MRR = 0 的 Case 数 | 4 |
| MRR > 0 的 Case 数 | 46 |
| first_relevant_rank = 1 | 34 |
| first_relevant_rank = 2 | 8 |
| first_relevant_rank = 3 | 4 |
| first_relevant_rank = None | 4 |
| nDCG@5 = 1.0 | 30 |
| nDCG@5 ∈ [0.5, 1.0) | 16 |
| nDCG@5 = 0.0 | 4 |

### 最差 10 Case（按 Hit → Recall → MRR → nDCG 排序）

| case_id | Hit@5 | Recall@5 | MRR | nDCG@5 |
|---------|-------|----------|-----|--------|
| q013 | 0.0 | 0.0 | 0.0 | 0.0 |
| q019 | 0.0 | 0.0 | 0.0 | 0.0 |
| q039 | 0.0 | 0.0 | 0.0 | 0.0 |
| q047 | 0.0 | 0.0 | 0.0 | 0.0 |
| q031 | 1.0 | 0.5 | 1.0 | 0.613147 |
| q034 | 1.0 | 0.5 | 1.0 | 0.613147 |
| q036 | 1.0 | 0.666667 | 1.0 | 0.703918 |
| q016 | 1.0 | 1.0 | 0.333333 | 0.5 |
| q041 | 1.0 | 1.0 | 0.333333 | 0.5 |
| q045 | 1.0 | 1.0 | 0.333333 | 0.5 |

---

## 4. 四个 Hit@5 = 0 的 Case

### 4.1 q013

- **Query**：模型并没有真的去查数据库，它回答里那些知识是从哪来的？为什么不能当最新事实用？
- **Gold 文件**：`llm/预训练.md`（大模型预训练：目标、数据、Tokenizer与分布式训练）
- **Top-5 retrieved files**：
  1. `rag/检索与生成.md`（RAG 检索与生成：在线请求完整链路）
  2. `agent_frameworks/LangChain-LangGraph-04-并行错误处理与测试.md`
  3. `vector_db/产品对比.md`
  4. `post_training/后训练-01-概念与偏好数据.md`
  5. `deployment/部署架构.md`

| rank | chunk_id | document_id | relative_path | dense_rank | sparse_rank | rrf_score | score |
|------|----------|-------------|---------------|-----------|-------------|-----------|-------|
| 1 | 7f0e0301d9690995d01e2857371c369f | 076bfdb158a7f47a | rag/检索与生成.md | 1 | 3 | 0.032266 | 0.636576 |
| 2 | 858659bee412633a6fc3962dec3209f5 | 9938360d2e8b9bf8 | agent_frameworks/LangChain-LangGraph-04-并行错误处理与测试.md | 6 | 20 | 0.027652 | 0.547764 |
| 3 | 9a284d8ccf4aecf21597730549a4a1f2 | 58900e3c6745e029 | vector_db/产品对比.md | 25 | 4 | 0.027390 | 0.526185 |
| 4 | 8ff0f32990268cea93890e876b27930a | 76845213c6564bfd | post_training/后训练-01-概念与偏好数据.md | 8 | 19 | 0.027364 | 0.546413 |
| 5 | b335858d46454b77e075316476188aa7 | 1094a22883135a7d | deployment/部署架构.md | 22 | 11 | 0.026280 | 0.532807 |

- **错误召回文档与 Gold 的主题关系**：Gold 文档主题是“预训练（知识从哪来、为什么不能当最新事实）”；Top-5 全部是应用/链路/架构/后训练类文档（RAG 在线链路、Agent 工作流、向量库选型、后训练、部署）。这些文档与查询中的“知识来源 / 最新事实 / 生成回答”语义邻近，但不是 Gold 文档主题。
- **初步失败类型**：semantic-neighbor confusion（最终 Top-5 被语义邻近的应用链路文档占据）。
- **证据边界**：Gold 是否进入 Dense/BM25 通道候选、在通道内的排名，现有 Artifact 无法判断。

### 4.2 q019

- **Query**：同一个模型，为什么训练时能一口气算完整段话的损失，生成时却只能一个字一个字地往外蹦？
- **Gold 文件**：`llm/Transformer架构-03-训练推理与高效Attention.md`
- **Top-5 retrieved files**：
  1. `llm/对齐与微调.md`
  2. `llm/预训练.md`
  3. `llm/Transformer架构-01-Attention与基础组件.md`
  4. `post_training/后训练-05-RM细节与GRPO应用.md`
  5. `prompt/提示工程基础.md`

| rank | chunk_id | document_id | relative_path | dense_rank | sparse_rank | rrf_score | score |
|------|----------|-------------|---------------|-----------|-------------|-----------|-------|
| 1 | 31fa9ff5163a427f7a9df5e1d589b511 | 50d6f867cf7f44ac | llm/对齐与微调.md | 13 | 1 | 0.030092 | 0.450888 |
| 2 | fa97e58546d97c2ee3e43a82b3c4011b | 4d1d69ed088b003f | llm/预训练.md | 6 | 11 | 0.029236 | 0.468823 |
| 3 | 072399c4dc097b7adc936465e3ce09ca | c388c364081aa999 | llm/Transformer架构-01-Attention与基础组件.md | 23 | 4 | 0.027673 | 0.442286 |
| 4 | d6fcb6a2494047b3aeb920c9bfe84e2e | 9736390396a7a649 | post_training/后训练-05-RM细节与GRPO应用.md | 9 | 25 | 0.026257 | 0.461704 |
| 5 | 91625ac3e51359af0dd3588200ab528d | 52daf25593c024a3 | prompt/提示工程基础.md | 15 | 20 | 0.025833 | 0.448842 |

- **错误召回文档与 Gold 的主题关系**：Gold 是 Transformer 系列第 03 篇（训练/推理/高效 Attention）；Top-5 中 rank 3 是**同系列第 01 篇（同标题“Transformer 架构：从张量到大模型推理”）**，另外包含对齐/预训练/后训练/提示工程。Gold 与 rank 3 文档属于同一文档系列且标题完全相同，属于强语义邻居。
- **初步失败类型**：semantic-neighbor confusion（同系列同标题文档抢占最终排名）；同标题系列文档可能叠加 chunk-boundary / 表达问题，但现有 Artifact 无法验证。
- **证据边界**：Gold（Transformer-03）在通道候选中的情况无法判断。

### 4.3 q039

- **Query**：为什么不能先检索出用户无权访问的文档，再要求模型保证不泄露？这类权限过滤应该在哪个阶段完成？
- **Gold 文件**：`rag/检索与生成.md`（RAG 检索与生成：在线请求完整链路）
- **Top-5 retrieved files**：
  1. `rag/文档处理.md`
  2. `tool_calling/Function-Calling原理.md`
  3. `deployment/部署架构.md`
  4. `tool_calling/工具设计.md`
  5. `vector_db/核心概念.md`

| rank | chunk_id | document_id | relative_path | dense_rank | sparse_rank | rrf_score | score |
|------|----------|-------------|---------------|-----------|-------------|-----------|-------|
| 1 | 3786baffca55445ea949553be5cb0530 | d53277e8d1dce368 | rag/文档处理.md | 6 | 10 | 0.029437 | 0.593585 |
| 2 | 7fdbf870e77fc077e589f49cf95a3143 | 420fc785a87e73e4 | tool_calling/Function-Calling原理.md | 13 | 12 | 0.027588 | 0.579238 |
| 3 | b335858d46454b77e075316476188aa7 | 1094a22883135a7d | deployment/部署架构.md | 10 | 19 | 0.026944 | 0.584791 |
| 4 | cf0ab1d4b776f3dec60ca213ff959c8f | fa46d9981425ca38 | tool_calling/工具设计.md | 30 | 4 | 0.026736 | 0.552267 |
| 5 | 0ef7ba64e882a1d1e585e9811f8b756d | 263a596a15bde15e | vector_db/核心概念.md | 9 | 23 | 0.026541 | 0.585639 |

- **错误召回文档与 Gold 的主题关系**：Gold 是 RAG 在线链路（权限/检索/生成）；Top-5 是 RAG 文档处理、Function Calling、部署、工具设计、向量库核心概念——都涉及“安全边界/权限/阶段划分”这一邻域，但没有进入 Gold 文档。
- **初步失败类型**：semantic-neighbor confusion（权限与安全边界语义分散在多个邻近文档）；同时查询中包含“检索/权限”词，Gold 内对应表达是否被检索命中无法判断。
- **证据边界**：Gold 在通道候选中的情况无法判断。

### 4.4 q047

- **Query**：为什么把生成温度调低并不能从根本上消除幻觉？
- **Gold 文件**：`llm/Transformer架构-04-采样与工程联系.md`
- **Top-5 retrieved files**：
  1. `prompt/评估与优化.md`
  2. `rag/高级RAG.md`
  3. `deployment/部署架构.md`
  4. `finetuning/微调方法.md`
  5. `prompt/提示工程高级技巧.md`

| rank | chunk_id | document_id | relative_path | dense_rank | sparse_rank | rrf_score | score |
|------|----------|-------------|---------------|-----------|-------------|-----------|-------|
| 1 | 6a495148064683a6da882569d014f2f7 | 5fcddd69127d9078 | prompt/评估与优化.md | 10 | 3 | 0.030159 | 0.416590 |
| 2 | 25e2df224eda743869bc2c257c487824 | b9ed7f314b155cbc | rag/高级RAG.md | 6 | 8 | 0.029857 | 0.430495 |
| 3 | b335858d46454b77e075316476188aa7 | 1094a22883135a7d | deployment/部署架构.md | 4 | 14 | 0.029139 | 0.432990 |
| 4 | 7550e266e76533bb89d5469722c80d2e | a2fa4c500d30389c | finetuning/微调方法.md | 5 | 17 | 0.028372 | 0.430970 |
| 5 | 6cc786bbabbe6da7b6c078f4de00b4af | fca1b07e02ccfa1f | prompt/提示工程高级技巧.md | 22 | 7 | 0.027120 | 0.391653 |

- **错误召回文档与 Gold 的主题关系**：Gold 是 Transformer 第 04 篇（采样与工程联系，温度/幻觉相关）；Top-5 是评估优化、高级 RAG、部署、微调、提示工程——都属于“幻觉缓解/质量优化”邻域，但没有进入 Gold 文档。
- **初步失败类型**：semantic-neighbor confusion（幻觉缓解语义被多个邻近文档分散占用最终排名）。
- **证据边界**：Gold 在通道候选中的情况无法判断。

---

## 5. 三个 Recall < 1 的 Multi-file Case

### 5.1 q031

- **Query**：从笔记文件到用户看到带引用的回答，『证据进索引』和『证据进上下文』分别由 RAG 的哪条链路负责？
- **Gold 文件（2）**：
  - `rag/文档处理.md`（RAG 文档处理：从文件到可检索索引）
  - `rag/检索与生成.md`（RAG 检索与生成：在线请求完整链路）
- **Top-5 retrieved files（去重后 2 个）**：`rag/检索与生成.md`、`rag/高级RAG.md`
- **指标**：Hit@5=1.0，Recall@5=0.5，MRR=1.0，nDCG@5=0.613147，first_relevant_rank=1

| rank | chunk_id | document_id | relative_path | dense_rank | sparse_rank | rrf_score | score |
|------|----------|-------------|---------------|-----------|-------------|-----------|-------|
| 1 | d3dbe0b0176ab854c05f3a0b7ff99650 | 076bfdb158a7f47a | rag/检索与生成.md | 1 | 1 | 0.032787 | 0.656104 |
| 2 | 7f0e0301d9690995d01e2857371c369f | 076bfdb158a7f47a | rag/检索与生成.md | 5 | 3 | 0.031258 | 0.586420 |
| 3 | 0103c7d9a05c64d37ab20e5fd56acb59 | b9ed7f314b155cbc | rag/高级RAG.md | 4 | 7 | 0.030550 | 0.598321 |
| 4 | 9cddac7ac37f79f19ef6904301b69a28 | b9ed7f314b155cbc | rag/高级RAG.md | 11 | 4 | 0.029710 | 0.530618 |
| 5 | afa8c3b94a9149cf6373578cc249911b | 076bfdb158a7f47a | rag/检索与生成.md | 8 | 8 | 0.029412 | 0.540877 |

- **错误/缺失分析**：Gold 之一（`rag/检索与生成.md`）在 rank 1 命中；另一个 Gold（`rag/文档处理.md`，负责“证据进索引”的离线链路）未进入 Top-5。错误召回文档 `rag/高级RAG.md` 与查询的“评测/高级策略”语义邻近，与缺失 Gold 不属于同一文件。
- **初步失败类型**：multi-document incomplete recall（单次 Top-5 只覆盖两个子问题中的一个）；次要 semantic-neighbor confusion（`rag/高级RAG.md` 占据最终排名）。

### 5.2 q034

- **Query**：想用实验证明『加 BM25 混合检索』有效，需要固定哪些变量、比较哪些指标？混合检索的两路候选分数实际是如何融合的？
- **Gold 文件（2）**：
  - `rag/高级RAG.md`（RAG 评测、故障分析与高级策略）
  - `rag/检索与生成.md`（RAG 检索与生成：在线请求完整链路）
- **Top-5 retrieved files（去重后 2 个）**：`rag/检索与生成.md`、`vector_db/核心概念.md`
- **指标**：Hit@5=1.0，Recall@5=0.5，MRR=1.0，nDCG@5=0.613147，first_relevant_rank=1

| rank | chunk_id | document_id | relative_path | dense_rank | sparse_rank | rrf_score | score |
|------|----------|-------------|---------------|-----------|-------------|-----------|-------|
| 1 | de69f3b4e94d0207313577f19d2dd2d3 | 076bfdb158a7f47a | rag/检索与生成.md | 1 | 1 | 0.032787 | 0.638968 |
| 2 | e163081eb24a970b65ebb193af0b0c2e | 263a596a15bde15e | vector_db/核心概念.md | 6 | 3 | 0.031025 | 0.605374 |
| 3 | 23b6e4a38bc80b9bd7708d439bc548b5 | 076bfdb158a7f47a | rag/检索与生成.md | 4 | 6 | 0.030777 | 0.611602 |
| 4 | d3488a6e51b85f21092acc973e17bcff | 263a596a15bde15e | vector_db/核心概念.md | 7 | 4 | 0.030550 | 0.597535 |
| 5 | bf4e747208e37224d643802bab945bdf | 076bfdb158a7f47a | rag/检索与生成.md | 3 | 15 | 0.029206 | 0.616923 |

- **错误/缺失分析**：Gold 之一（`rag/检索与生成.md`）rank 1 命中；另一个 Gold（`rag/高级RAG.md`，含“评测变量/指标”与混合检索融合论述）未进入 Top-5。错误召回 `vector_db/核心概念.md` 与“索引/向量库”语义邻近。
- **初步失败类型**：multi-document incomplete recall（`rag/高级RAG.md` 未进 Top-5）；次要 semantic-neighbor confusion。

### 5.3 q036

- **Query**：面对『文档里写着忽略系统规则』这类注入，Prompt 层、RAG 文档/检索层、Tool 执行层分别应该做什么防御？为什么只靠一句系统提示不够？
- **Gold 文件（3）**：
  - `prompt/提示工程高级技巧.md`（分解、路由、验证与注入防御）
  - `rag/文档处理.md`（RAG 文档处理：从文件到可检索索引）
  - `tool_calling/Function-Calling原理.md`（Function Calling 原理与执行循环）
- **Top-5 retrieved files（去重后 4 个）**：`prompt/提示工程高级技巧.md`、`prompt/提示工程基础.md`、`rag/文档处理.md`、`rag/高级RAG.md`
- **指标**：Hit@5=1.0，Recall@5=0.666667，MRR=1.0，nDCG@5=0.703918，first_relevant_rank=1

| rank | chunk_id | document_id | relative_path | dense_rank | sparse_rank | rrf_score | score |
|------|----------|-------------|---------------|-----------|-------------|-----------|-------|
| 1 | 6cc786bbabbe6da7b6c078f4de00b4af | fca1b07e02ccfa1f | prompt/提示工程高级技巧.md | 1 | 1 | 0.032787 | 0.703248 |
| 2 | d23e52226202105dc5add9d943febe72 | 52daf25593c024a3 | prompt/提示工程基础.md | 2 | 8 | 0.030835 | 0.664994 |
| 3 | abf9618fe5c04bc64b8ebe4a3c98b073 | d53277e8d1dce368 | rag/文档处理.md | 11 | 2 | 0.030214 | 0.630603 |
| 4 | a4cf3dac09c0915db04aa5564a44894c | fca1b07e02ccfa1f | prompt/提示工程高级技巧.md | 3 | 12 | 0.029762 | 0.661597 |
| 5 | eada04f5d3fd3e8fbd6328313296bde5 | b9ed7f314b155cbc | rag/高级RAG.md | 15 | 10 | 0.027619 | 0.623643 |

- **错误/缺失分析**：3 个 Gold 中命中 2 个（`提示工程高级技巧` rank 1、`rag/文档处理` rank 3）；缺失 `tool_calling/Function-Calling原理.md`（查询中明确问 Tool 执行层防御）。错误召回 `prompt/提示工程基础.md` 与 `rag/高级RAG.md` 均属提示/检索安全邻域。
- **初步失败类型**：multi-document incomplete recall（partial，3 取 2）；次要 semantic-neighbor confusion。

---

## 6. 失败类型汇总

| case_id | 主要分类 | 次要分类 | 证据等级 |
|---------|----------|----------|----------|
| q013 | semantic-neighbor confusion | 无 | 最终 Top-5 事实明确；通道证据不足 |
| q019 | semantic-neighbor confusion（同系列同标题文档） | possible chunk-boundary issue（无法验证） | 最终 Top-5 事实明确；通道/分块证据不足 |
| q039 | semantic-neighbor confusion | 无 | 最终 Top-5 事实明确；通道证据不足 |
| q047 | semantic-neighbor confusion | 无 | 最终 Top-5 事实明确；通道证据不足 |
| q031 | multi-document incomplete recall | semantic-neighbor confusion | 事实明确（1/2 Gold 未进 Top-5） |
| q034 | multi-document incomplete recall | semantic-neighbor confusion | 事实明确（1/2 Gold 未进 Top-5） |
| q036 | multi-document incomplete recall | semantic-neighbor confusion | 事实明确（2/3 Gold 命中，1 个缺失） |

所有 4 个 Hit@5=0 的 Case，其 Gold 是否进入任一通道候选、通道内排名如何，**现有 Artifact 无法判断**，需要后续 channel-level diagnostic / ablation。

---

## 7. 下一步实验假设（只提出，不执行）

### H1：失败主要来自 Dense / BM25 都偏向语义邻居

- **状态**：plausible / currently unverified（通道层）
- 事实支撑：4 个全失败 Case 的最终 Top-5 全部是语义邻近文档；但没有通道候选快照，无法证明两个通道都偏向邻居。

### H2：正确文档进入某一通道候选，但 RRF 融合后排名丢失

- **状态**：currently unverified
- 现有 Artifact 只保存最终 Top-5 Hit 的 dense/sparse rank，无法判断“候选命中但 RRF 丢失”是否发生。

### H3：Chunk 边界让 Gold 文档中的目标证据表达被削弱

- **状态**：plausible / currently unverified
- q019 的 Gold 与 rank 3 命中文档同标题同系列，存在分块/标题表达干扰的可能性；其余 Case 需要 chunk-level 检查才能验证。

### H4：Multi-file Query 在单次 Retrieval 下天然只覆盖部分子问题

- **状态**：supported
- 事实支撑：q031 / q034 / q036 均为多 Gold 文件查询，Top-5 各命中 1 个（q036 命中 2/3），缺失文件与查询中未被覆盖的子问题直接对应（“证据进索引”链路、混合检索评测/融合、Tool 执行层防御）。

---

## 8. 数据来源

- `experiments/874b61d0b5d1/agent-ai-v1-recursive-hybrid-baseline-001/result.json`
- `experiments/874b61d0b5d1/agent-ai-v1-recursive-hybrid-baseline-001/index_manifest.json`
- `experiments/874b61d0b5d1/agent-ai-v1-recursive-hybrid-baseline-001/retrieval_results.json`
- `experiments/874b61d0b5d1/agent-ai-v1-recursive-hybrid-baseline-001/retrieval_metrics.json`
- `D:\学习\rag实战项目\rag数据集\benchmark_work\agent_ai_v1\04_gold\evaluation.jsonl`（只读）
- `D:\学习\rag实战项目\rag数据集\benchmark_work\agent_ai_v1\02_corpus_candidate`（只读）
