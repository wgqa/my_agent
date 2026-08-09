# 学习笔记索引（docs/study-notes/）

> **顶部声明**：本文件是 `docs/study-notes/` 全部学习笔记的索引。每份笔记**只出现一次**，按状态分为四类：`CURRENT` / `FROZEN_EVIDENCE` / `SUPERSEDED` / `HISTORY`。本索引只做索引，**不修改任何原始笔记**。

**分类规则**

- `CURRENT`：描述当前仍适用的契约、状态、基础设施或方法论，直接指导后续任务。
- `FROZEN_EVIDENCE`：记录 Gate 2 冻结实验/评测证据；其中数字一律以 `docs/experiments/gate2_freeze.json` 为权威来源，本类笔记是证据链与学习参考，不是可更新的现状文档。
- `SUPERSEDED`：行为已被后续修复取代，标注替代目标（见各条）。
- `HISTORY`：早期模块学习笔记与阶段/修复过程记录，非当前权威参考；当前行为以代码、测试与 `docs/status.md` 为准。

**权威来源分层**（与 `docs/roadmap.md` §2.1 一致）

| 信息 | 真相来源 |
|---|---|
| 实现事实 | 最新代码与测试 |
| 当前实时任务 | `docs/status.md` |
| 长期路线 | `docs/roadmap.md` |
| Gate 2 冻结数字与结论 | `docs/experiments/gate2_freeze.json` |
| 快速交接 | `docs/HANDOFF.md` |
| 设计演进与学习历史 | 本目录（docs/study-notes 与 docs/archive） |

---

## CURRENT（15 份）

| 编号 | 笔记 | 说明 |
|---:|---|---|
| 00 | [00-learning-workflow.md](00-learning-workflow.md) | 学习流程方法论 |
| 34 | [34-rework-p0-hybrid-bm25.md](34-rework-p0-hybrid-bm25.md) | REWORK-P0：Hybrid 候选链路 + BM25 统计修复后的当前行为 |
| 35 | [35-rework-p0-03-token-chunk-lossless.md](35-rework-p0-03-token-chunk-lossless.md) | 当前 TokenCounter/Chunker 数据边界模型（文本为事实源、token 只做预算） |
| 36 | [36-rework-p0-03-r2-audit-fixes.md](36-rework-p0-03-r2-audit-fixes.md) | 当前分块契约（假阳性测试、死代码 overlap、复杂度修正） |
| 38 | [38-rebuild-sparse-strict.md](38-rebuild-sparse-strict.md) | `_rebuild_sparse_index` 严格模式（当前行为） |
| 39 | [39-experiment-config.md](39-experiment-config.md) | ExperimentConfig 强类型实验配置（当前基础设施） |
| 40 | [40-experiment-workspace.md](40-experiment-workspace.md) | ExperimentWorkspace 独立实验工作区（当前基础设施） |
| 42 | [42-experiment-corpus.md](42-experiment-corpus.md) | ExperimentCorpus 可复现语料清单（当前基础设施） |
| 43 | [43-hybrid-rrf-absent-channel.md](43-hybrid-rrf-absent-channel.md) | RRF 缺席通道贡献必须为 0（当前契约） |
| 45 | [45-experiment-runner-index-manifest.md](45-experiment-runner-index-manifest.md) | 可复现入库与原子 Index Manifest（当前基础设施） |
| 46 | [46-retrieval-evaluation-set.md](46-retrieval-evaluation-set.md) | RetrievalEvaluationSet 文档级标注与稳定 evaluation_set_id（当前基础设施） |
| 47 | [47-retrieval-execution.md](47-retrieval-execution.md) | 正式检索执行与原始结果快照（当前基础设施） |
| 48 | [48-retrieval-metrics.md](48-retrieval-metrics.md) | 文档级指标与原子指标快照（当前基础设施） |
| 49 | [49-experiment-result.md](49-experiment-result.md) | ExperimentResult 事实快照绑定（当前基础设施） |
| 50 | [50-experiment-orchestrator.md](50-experiment-orchestrator.md) | 单实验端到端 Orchestrator（当前基础设施） |

## FROZEN_EVIDENCE（10 份）

| 编号 | 笔记 | 说明 |
|---:|---|---|
| 51 | [51-baseline-error-analysis.md](51-baseline-error-analysis.md) | 第一次真实 Baseline Retrieval Error Analysis（G2-ANALYSIS-12） |
| 52 | [52-channel-diagnostics-and-rrf-tie.md](52-channel-diagnostics-and-rrf-tie.md) | Hybrid Channel-Level Diagnostic 与 RRF 平局发现（G2-DIAG-13） |
| 53 | [53-rrf-tie-python-hash-reproducibility.md](53-rrf-tie-python-hash-reproducibility.md) | RRF 平局、Python Hash 随机化与可复现（G2-DIAG-13-R1） |
| 54 | [54-Chunk级检索、文档级Gold与Hybrid融合粒度.md](54-Chunk级检索、文档级Gold与Hybrid融合粒度.md) | Chunk 级检索、文档级 Gold 与融合粒度（G2-ANALYSIS-14） |
| 55 | [55-Dense、BM25与Hybrid消融实验.md](55-Dense、BM25与Hybrid消融实验.md) | Dense/BM25/Hybrid 消融（G2-ABL-15） |
| 56 | [56-离线消融与正式可复现实验.md](56-离线消融与正式可复现实验.md) | 离线消融与正式可复现实验（G2-ABL-16） |
| 57 | [57-Fixed与Recursive分块消融实验.md](57-Fixed与Recursive分块消融实验.md) | Fixed 与 Recursive 分块消融（G2-ABL-17） |
| 58 | [58-Tokenizer对齐与Embedding截断.md](58-Tokenizer对齐与Embedding截断.md) | Tokenizer 对齐与 Embedding 截断（G2-DIAG-18） |
| 59 | [59-BGE对齐分块与干预实验.md](59-BGE对齐分块与干预实验.md) | BGE 对齐分块与干预实验（G2-ABL-21） |
| 60 | [60-Gate2评测体系与RAG实验方法总结.md](60-Gate2评测体系与RAG实验方法总结.md) | Gate 2 评测体系与 RAG 实验方法总结（G2-CLOSE-22） |

## SUPERSEDED（1 份）

| 编号 | 笔记 | 说明 | 替代目标 |
|---:|---|---|---|
| 28 | [28-token-counter-and-chunker-fix.md](28-token-counter-and-chunker-fix.md) | 早期 TokenCounter/Chunker 修复方案；已被 REWORK-P0-03 推翻重做 | [35](35-rework-p0-03-token-chunk-lossless.md) |

## HISTORY（35 份）

| 编号 | 笔记 | 说明 |
|---:|---|---|
| 01 | [01-loader-base.md](01-loader-base.md) | 早期模块学习记录：Loader 基类 |
| 02 | [02-loader-pdf.md](02-loader-pdf.md) | 早期模块学习记录：PDF Loader |
| 03 | [03-loader-text.md](03-loader-text.md) | 早期模块学习记录：文本 Loader |
| 04 | [04-loader-code.md](04-loader-code.md) | 早期模块学习记录：代码 Loader |
| 05 | [05-chunker-base.md](05-chunker-base.md) | 早期模块学习记录：Chunker 基类 |
| 06 | [06-chunker-fixed-size.md](06-chunker-fixed-size.md) | 早期模块学习记录：FixedSize Chunker |
| 07 | [07-chunker-recursive.md](07-chunker-recursive.md) | 早期模块学习记录：Recursive Chunker |
| 08 | [08-chunker-semantic.md](08-chunker-semantic.md) | 早期模块学习记录：Semantic Chunker（实验性） |
| 09 | [09-embeddings-base.md](09-embeddings-base.md) | 早期模块学习记录：Embedding 基类 |
| 10 | [10-embeddings-openai.md](10-embeddings-openai.md) | 早期模块学习记录：OpenAI Embedding |
| 11 | [11-embeddings-bge.md](11-embeddings-bge.md) | 早期模块学习记录：BGE Embedding |
| 12 | [12-vectorstore-base.md](12-vectorstore-base.md) | 早期模块学习记录：VectorStore 基类 |
| 13 | [13-vectorstore-chroma.md](13-vectorstore-chroma.md) | 早期模块学习记录：Chroma VectorStore |
| 14 | [14-retriever-base.md](14-retriever-base.md) | 早期模块学习记录：Retriever 基类 |
| 15 | [15-retriever-simple.md](15-retriever-simple.md) | 早期模块学习记录：Simple Retriever |
| 16 | [16-retriever-mmr.md](16-retriever-mmr.md) | 早期模块学习记录：MMR Retriever |
| 17 | [17-retriever-hybrid.md](17-retriever-hybrid.md) | 早期模块学习记录：Hybrid Retriever |
| 18 | [18-reranker-base.md](18-reranker-base.md) | 早期模块学习记录：Reranker 基类 |
| 19 | [19-reranker-bge.md](19-reranker-bge.md) | 早期模块学习记录：BGE Reranker |
| 20 | [20-generator-base.md](20-generator-base.md) | 早期模块学习记录：Generator 基类 |
| 21 | [21-generator-deepseek.md](21-generator-deepseek.md) | 早期模块学习记录：DeepSeek Generator |
| 22 | [22-generator-openai.md](22-generator-openai.md) | 早期模块学习记录：OpenAI Generator |
| 23 | [23-pipeline.md](23-pipeline.md) | 早期模块学习记录：Pipeline |
| 24 | [24-eval-metrics.md](24-eval-metrics.md) | 早期评测实现记录：指标（legacy Evaluator） |
| 25 | [25-eval-evaluator.md](25-eval-evaluator.md) | 早期评测实现记录：Evaluator（legacy，与正式 ExperimentRunner 并存） |
| 26 | [26-eval-report.md](26-eval-report.md) | 早期评测实现记录：报告（legacy Evaluator） |
| 27 | [27-eval-quality.md](27-eval-quality.md) | 早期评测实现记录：质量评估（legacy Evaluator） |
| 29 | [29-phase1-fix-summary.md](29-phase1-fix-summary.md) | Phase 1：RAG 管线正确性修复（阶段总结） |
| 30 | [30-bug-fix-summary.md](30-bug-fix-summary.md) | Bug 修复总结（2026-07-24） |
| 31 | [31-m0-engineering-baseline.md](31-m0-engineering-baseline.md) | M0 工程基线（里程碑记录） |
| 32 | [32-m1-data-correctness.md](32-m1-data-correctness.md) | M1 入库与数据正确性（里程碑记录） |
| 33 | [33-m3-context-citation.md](33-m3-context-citation.md) | M3 上下文、生成与引用（里程碑记录） |
| 37 | [37-eval-integrity-fixes.md](37-eval-integrity-fixes.md) | legacy Evaluator 的评测完整性修复记录；Gate 2 正式实验路径以 ExperimentRunner 45～50 为准 |
| 41 | [41-experiment-runner.md](41-experiment-runner.md) | ER-03 最小 Runner 阶段记录，当时仍不索引、不评测；完整正式流程见 45～50 |
| 44 | [44-gate1-close.md](44-gate1-close.md) | Gate 1 收口里程碑；当前实时阶段以 docs/status.md 为准 |

---

## 完整性声明

- 编号覆盖 00–60 共 **61 份**，每份只出现一次：CURRENT 15 + FROZEN_EVIDENCE 10 + SUPERSEDED 1 + HISTORY 35 = 61。
- 原始笔记一律未修改。
- 当前日期：2026-08-09。
