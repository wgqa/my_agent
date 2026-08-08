# 项目状态

> 唯一的实时状态表。每次里程碑/修复后更新本文件。
> 历史大规划已归档至 `docs/archive/`，以本文件为真相来源。

**更新日期：** 2026-08-08

## 当前结论

- **定位**：面向技术文档与代码的可评测 RAG Agent
- **阶段**：M0-M3 + REWORK-P0 + 评测阻塞修复（E-01~04）+ ER-01~04 完成 → **Gate 1（基础 RAG 可信状态）已通过** → **G2-ER-05 ExperimentRunner 入库功能复审通过** → **G2-EVAL-06 RetrievalEvaluationSet 复审通过** → **G2-EVAL-07 正式检索执行与原始结果快照复审通过** → **G2-EVAL-08 文档级 Retrieval Metrics 复审通过** → **G2-EVAL-09 ExperimentResult 最终实验摘要复审通过** → **G2-EXP-10 单实验端到端 Orchestrator 复审通过** → **G2-REAL-11 第一次真实 agent_ai_v1 Retrieval Baseline（pre-binding + R1 embedding-bound）复审通过** → **G2-ANALYSIS-12 第一次真实 Baseline Error Analysis 复审通过** → **G2-DIAG-13/R1 Hybrid Channel-Level Diagnostic：RRF tie 确定化 + canonical Baseline + 50/50 复审通过** → **G2-ANALYSIS-14 Chunk-Level Fusion Fragmentation Analysis 复审通过** → **G2-ABL-15/R1 Dense vs BM25 vs Hybrid offline channel ablation 复审通过** → **G2-ABL-16/R1 Dense-only / BM25-only Formal Strategy Confirmation 复审通过** → **G2-ABL-17/R1 Fixed vs Recursive Chunk Strategy Formal Ablation 复审通过** → **G2-DIAG-18/R1/R2/R3 Chunk Budget vs BGE Tokenizer Alignment Diagnostic 复审通过** → **G2-DESIGN-19/R1/R2 BGE-Aligned Chunk Budget Intervention Contract 复审通过** → **G2-IMPL-20/R1 BGE-Aligned Chunk Budget Infrastructure 复审通过** → **G2-ABL-21/R1 BGE-Aligned Chunk Budget Formal Retrieval Ablation 复审通过** → **G2-CLOSE-22/R1 Gate 2 Final Review / Evidence Synthesis / Benchmark Freeze（完成，待复审）** → **Gate 1 = CLOSED；Gate 2 = G2-CLOSE-22-R1 final closure review；Gate 3 = not started；next = Query Decomposition / Adaptive Retrieval**
- **测试**：全量 suite 通过（--basetemp=.tmp_pytest）

## 任务状态

| 里程碑 | 状态 | 说明 | 验收要点 |
|--------|------|------|---------|
| M0 工程基线 | ✅ | T1-T4 | git 初始化 / baseline.md / 测试隔离 / config Fail-Fast / README |
| M1 数据正确性 | ✅ | T1-T6 | 领域模型 / ChromaStore 契约 / 统一 Token 计数 / chunker 修复 / Loader 元数据 / 幂等入库 |
| M2 检索验证 | ✅ | 08-03 收尾 | Dense fixture / Sparse 补召回 / Reranker 降级 |
| M3 上下文/生成/引用 | ✅ | T1-T6（08-03） | ContextAssembler / Prompt 重写 / 引用验证 / 拒答 / Generator 可靠性 / 多轮对话 |
| REWORK-P0-01 | ✅ | 08-05 复审通过 | Hybrid 候选链路 |
| REWORK-P0-02 | ✅ | 08-05 复审通过 | BM25 统计膨胀 + ID 错位 |
| REWORK-P0-03 | ✅ | 08-05 R2 复审通过 | TokenCounter/Chunker 静默丢字 + 严格预算 + 真实 overlap |
| M4 评测与消融 | ⬜ | Gate 2 evaluation/ablation completed, pending final closure review | — |
| M5/M6 | ⏭ | 计划跳过大部分，仅做 Docker | — |
| Agent（结构化 Tool） | ⬜ | M4 之后 | — |

## 修复清单

| # | 问题 | 修复 | 状态 |
|---|------|------|------|
| P0-1 | rerank 分数未写回，assembler 按稠密分重排 | 写回 rerank_score/final_rank；按 rerank 排序 | ✅ 08-05 复审通过 |
| P0-2 | 更新先删旧数据 | 先写后删 | ✅ |
| P0-3 | reranker 死配置 | pipeline 接线 | ✅ |
| P0-4 | TokenCounter 乱码 | 见 REWORK-P0-03（推翻重做） | ✅ |
| P0-5 | 实验脚本旧 API | 改用现行 API | ✅ |
| REWORK-P0-01 | candidate_k 被 internal final_k 截断 | 池取 max(final_k, top_k)；top_k 语义明确 | ✅ 复审通过 |
| REWORK-P0-02 | BM25 重复入库统计膨胀 + zip 错位 | add_document 真 upsert；全量 idf；_batch 写回 id | ✅ 复审通过 |
| REWORK-P0-03 | 分块静默丢字/乱码 | 文本为事实源 + token 只做预算（见 study-notes 35/36） | ✅ 08-05 R2 复审通过 |
| E-01 | 报告排序/展示查 hit_rate，生成端是 hit_at_k | 统一 hit_at_k（见 study-notes 37） | ✅ 复审通过 |
| E-02 | 跨 chunk_strategy 实验不重建索引，产出虚假对比 | run() 入口拒绝多值（见 study-notes 37） | ✅ 复审通过 |
| E-03 | Evaluator 重建 Retriever 后 Hybrid BM25 为空，退化为 Dense-only | _apply_config 后调 _rebuild_sparse_index（见 study-notes 37） | ✅ 复审通过 |
| E-04 | _rebuild_sparse_index 吞异常，"调用过"≠"重建成功" | strict 模式 fail-fast + 数量校验（见 study-notes 38） | ✅ 复审通过 |
| ER-01 | Evaluator 用无约束 dict 配置 | ExperimentConfig 强类型模型：构造即校验 + 稳定 experiment_id（见 study-notes 39） | ✅ 复审通过 |
| ER-02 | 实验共享同一 ChromaDB 索引 | ExperimentWorkspace 独立工作区 + 派生配置（见 study-notes 40） | ✅ 复审通过 |
| ER-03 | Pipeline 从 YAML 构建，未接通工作区 | ExperimentRunner 最小版：workspace → 派生配置 → 独立 Pipeline + 一致性校验（见 study-notes 41） | ✅ 复审通过 |
| ER-04 | 实验语料不固定，指标无法复现 | ExperimentCorpus：文件清单 + 字节 SHA-256 + 稳定 corpus_id（见 study-notes 42） | ✅ 复审通过 |
| ER-05 | 语料入库缺少可复现快照（无 Index Manifest） | ExperimentRunner.index_corpus：入库前完整性校验 + 确定性入库 + Dense/BM25 一致性 + 原子 index_manifest.json（见 study-notes 45） | ✅ 复审通过 |
| EVAL-06 | 旧 QAPair 使用 Chunk ID，无法跨 Fixed/Recursive 策略比较 | RetrievalEvaluationSet：JSONL 严格解析 + 文档级相关文件标注 + 稳定 evaluation_set_id（见 study-notes 46） | ✅ 复审通过 |
| EVAL-07 | 缺少正式检索执行与原始结果快照 | ExperimentRunner.run_retrieval：绑定校验 + 逐 Case 检索 + document_id→relative_path 映射 + 原子 retrieval_results.json（见 study-notes 47） | ✅ 复审通过 |
| EVAL-08 | 缺少文档级指标与原子指标快照 | ExperimentRunner.compute_retrieval_metrics：磁盘事实快照绑定 + Case 不变量 + Hit@K/Recall/MRR/nDCG + 宏平均 + 原子 retrieval_metrics.json（见 study-notes 48） | ✅ 复审通过 |
| EVAL-09 | 缺少单实验结果收口 | ExperimentRunner.finalize_result：三份落盘事实快照绑定 + 跨阶段 ID/数量校验 + 稳定 ExperimentResult + 原子 result.json（见 study-notes 49） | ✅ 复审通过 |
| EXP-10 | 缺少唯一高层实验入口 | ExperimentRunner.run_experiment：prepare → index_corpus → run_retrieval → compute_retrieval_metrics → finalize_result 固定顺序编排（见 study-notes 50） | ✅ 复审通过 |
| REAL-11 | 第一次真实 agent_ai_v1 Retrieval Baseline（pre-binding） | Recursive + Hybrid + top5：file_count=37、total_chunks=215、case_count=50；experiment_id=b8e4bdb3b942、result_id=8a08132354cc；Hit@5=0.92、Recall@5=0.893333、MRR=0.786667、nDCG@5=0.799360 | ✅ 复审通过 |
| REAL-11-R1 | Embedding Identity 纳入正式实验身份并重跑 | ExperimentConfig 新增 embedding_provider/embedding_model；experiment_id=874b61d0b5d1、result_id=325d94294803；Hit@5=0.92、Recall@5=0.893333、MRR=0.786667、nDCG@5=0.799360（与第一次完全一致） | ✅ 复审通过 |
| ANALYSIS-12 | 第一次真实 Baseline Retrieval Error Analysis | 4 个 Hit@5=0（q013/q019/q039/q047）+ 3 个 Recall<1（q031/q034/q036）事实分析；提出 H1-H4 实验假设（见 docs/experiments/agent_ai_v1_baseline_analysis.md、study-notes 51） | ✅ 复审通过 |
| DIAG-13 | Hybrid Dense/BM25 Channel-Level Diagnostic Snapshot | retrieve_with_trace + retrieval_diagnostics.json 已实现；修复前 50/50 验证受阻（RRF 平局顺序跨进程不稳定，见 study-notes 52） | ✅ 复审通过 |
| DIAG-13-R1 | RRF Deterministic Tie-Break + 实验身份绑定 | RRF 契约改为 rrf DESC + chunk_id ASC；rrf_tie_breaker 进入 ExperimentConfig/实验身份；canonical Baseline experiment_id=3c613202e1ed；diagnostic 50/50 exact match（见 study-notes 53） | ✅ 复审通过 |
| ANALYSIS-14 | Chunk-Level Fusion Fragmentation Analysis | 58 个 Gold obligations：A=0/B=0/C=1/D=27/E=27/F=3；Final 失败 7 条中 E+F=5、F=3；q039 确认 same-document/different-chunk（见 study-notes 54） | ✅ 复审通过 |
| ABL-15 | Dense vs BM25 vs Hybrid offline channel ablation | Dense Hit0.88/Recall0.8633/MRR0.7483/nDCG0.7624；BM25 Hit0.98/Recall0.9533/MRR0.7873/nDCG0.8206；Hybrid Hit0.92/Recall0.8933/MRR0.7867/nDCG0.7994；Hybrid vs Dense 修复4/损失2、vs BM25 修复0/损失3（R1 文档口径修正完成，见 study-notes 55） | ✅ 复审通过 |
| ABL-16 | Dense-only / BM25-only Formal Strategy Confirmation | 新增 bm25 策略（BM25OnlyRetriever）；正式 Dense Hit0.88/Recall0.8633/MRR0.7483/nDCG0.7624、BM25 Hit0.98/Recall0.9533/MRR0.7873/nDCG0.8206；offline vs formal 宏 delta 全 0，Case-level 与 chunk-level 均 50/50（见 study-notes 56） | ✅ 复审通过 |
| ABL-16-R1 | Runtime Retriever Binding + BM25 Sparse Integrity | _validate_pipeline 增加真实 Retriever 类型校验（simple/hybrid/bm25/mmr）；hybrid/bm25 强制 sparse_index_count==vector_store_count，simple 保持 null；未来 BM25 Manifest 将含 sparse count（见 study-notes 56） | ✅ 复审通过 |
| ABL-17 | Fixed vs Recursive Chunk Strategy Formal Ablation | CLI 新增 --chunk-strategy；三个 Fixed 正式实验（Dense Hit0.80/Recall0.7867/MRR0.6717/nDCG0.6896、BM25 Hit0.96/Recall0.9333/MRR0.7583/nDCG0.7892、Hybrid Hit0.92/Recall0.9133/MRR0.7600/nDCG0.7915）；total_chunks 237 三者一致；Fixed BM25/Hybrid sparse integrity=237 闭合；H3 拆分为 H3a（chunk strategy materially affects retrieval，supported）/ H3b（specific boundary 削弱证据，plausible/unverified）（见 study-notes 57） | ✅ 复审通过 |
| ABL-17-R1 | Chunk Ablation 方法论与学习笔记口径修正 | H3 拆分为 H3a/H3b；57 号笔记修正 TokenCounter 真实实现（tiktoken cl100k_base + 字符级 fallback）、新增"512 token 到底是谁的 token"、修正 BGE pooling 表述与 overlap 经验值；伪 citation 扫描为 0；零代码/零 Artifact 修改 | ✅ 复审通过 |
| DIAG-18 | Chunk Budget vs BGE Tokenizer Alignment Diagnostic | 主体诊断（独立 AutoTokenizer）：Recursive 215/Fixed 237 重建一致；would-truncate 34/215 与 35/237；登记 BPE monotonicity 技术债（见 study-notes 58） | ✅ 复审通过 |
| DIAG-18-R1 | Tokenizer Diagnostic 与实际 SentenceTransformer Runtime Binding | 长度契约绑定实际运行时：SentenceTransformer.max_seq_length=512、runtime BertTokenizer.model_max_length=512、effective=512；runtime tokenizer 带 Lowercase normalizer，独立 AutoTokenizer 低估长度；would-truncate 更新为 Recursive 57/215=26.51%、Fixed 71/237=29.96%；overflow max 195/196；diagnostic_id=51e18bf2cff6 绑定 runtime tokenizer/effective max；Level 2（实际截断）确认、Level 3（性能因果）仍 unverified（见 study-notes 58） | ✅ 复审通过 |
| DIAG-18-R2 | Runtime Tokenizer Behavior Fingerprint + Effective Max Contract 修正 | 新增 runtime_tokenizer_behavior_fingerprint（按 strategy/relative_path/chunk_index 稳定顺序对全部冻结 Chunk 的实际 input_ids 流式 SHA-256，取前 16 hex）；fingerprint 进入 diagnostic_id（同 class/max 不同行为 → ID 必变）；effective max 只由 SentenceTransformer.max_seq_length 定义（==512 fail-fast），tokenizer.model_max_length 仅作运行态事实记录（512/1024 均 pass，按 effective 判断截断）；同 class/max 不同 behavior 测试通过；新 diagnostic_id=801dda0b7ca0、fingerprint=1b865a1b28144ede；统计保持 57/71（见 study-notes 58） | ✅ 复审通过 |
| DIAG-18-R3 | 最终文档一致性修正 | 纯 Markdown：报告"约 15%"旧口径替换为 runtime 口径（57/215≈26.5%、71/237≈30.0%），34/35 仅保留为 R0/standalone 历史结果；Level 2（实际截断 confirmed）与 Level 3（性能因果 unverified）明确分离；fingerprint 表述收紧为 corpus-scoped；零代码/零 JSON Artifact 修改 | ✅ 复审通过 |
| DESIGN-19 | BGE-Aligned Chunk Budget Intervention Contract | 设计契约：model_input_budget=512 / special_token_overhead=2（runtime 实测）/ content_budget=510 / overlap 只用正文 token；chunk_size=512 在 aligned 模式下=model input budget；新增 chunk_budget_tokenizer 实验身份字段；EmbeddingRuntimeTokenCounter 方案；monotonicity 三选一（性质验证/安全搜索/post-condition fail-fast）；仅 Recursive+Dense/BM25/Hybrid 三实验矩阵，BM25 作 control；结果解释分级 A/B/C；旧 Baseline 字节不变（见 docs/design/g2_tokenizer_aligned_chunk_intervention.md） | ✅ 复审通过 |
| DESIGN-19-R1 | BGE-Aligned Chunk Budget Contract 身份与正确性收口 | 设计文档重写：拆分 tokenizer_contract_fingerprint（pre-run、probe suite v1、进 ExperimentConfig/experiment_id）与 corpus_scoped_tokenizer_behavior_fingerprint（post-index、进 Manifest）；chunk_budget_policy="cl100k_content_v1"/"embedding_runtime_model_input_v1" 收口身份；Counter 必须取自同一 BGEEmbedding 实例（get_runtime_tokenizer/get_runtime_contract 窄接口）；prepare 按 contract fingerprint fail-fast；monotonicity 改为 Step1-4 正式决策（先性质验证，反例则禁止二分）；corpus-scoped fingerprint 从正式 vector store 已入库 chunks 重算（chunk_id 稳定排序，count==vector==total）；Manifest 顶层只加 post-index observed facts；intervention 硬条件 actual_would_truncate_count==0 且 model_input_token_max<=max_seq_length（见设计文档） | ✅ 复审通过 |
| DESIGN-19-R2 | Runtime Contract Preflight 与 Final Experiment Identity Bootstrap | 设计文档追加：ExperimentSpec/Draft → Runtime Contract Resolver → frozen Final ExperimentConfig → experiment_id → Workspace → Pipeline 的严格生命周期（10 步写死）；Preflight 用本地只读 ST contract instance（local_files_only、不 encode、不建 Workspace）解析 max/overhead/probe/fingerprint；Preflight 与 Formal Pipeline 不要求同一对象但 behavior contract 必须完全一致（_validate_pipeline 重算比对 fail-fast）；Counter 仍用正式 Pipeline 同一模型实例；cl100k_content_v1 用 canonical sentinel 免 Preflight（只有 embedding_runtime_model_input_v1 需要）；probe suite 单一事实源（runtime_contract 共享模块）；唯一 resolver（resolve_config）；Preflight 失败在 Workspace 前退出；完整最终架构图与 7 条完成条件回答（见设计文档） | ✅ 复审通过 |
| IMPL-20 | BGE-Aligned Chunk Budget Infrastructure | 实现：core/embeddings/runtime_contract.py（probe v1 + contract/corpus fingerprint 唯一事实源）；BGEEmbedding get_runtime_model/tokenizer/contract 窄接口；ExperimentSpec + resolve_experiment_config（唯一 resolver，cl100k 免 Preflight）；ExperimentConfig 新增 chunk_budget_policy/max/overhead/probe/fingerprint 并进 to_dict/experiment_id（aligned 完整校验、cl100k 必须 None）；Config/Workspace 派生 YAML 读写校验；EmbeddingRuntimeTokenCounter（content/model-input 分离、正确性安全线性边界搜索、非单调 fake 通过）；Pipeline 注入同一模型实例 counter；_validate_pipeline runtime contract 重算比对 + counter 类型校验；index_corpus 从 vector store 重算 post-index observed facts（count==vector==total，would_truncate!=0 禁止成功 Manifest）；Manifest 顶层 observed fields；CLI --chunk-budget-policy；未运行真实 aligned 实验 | ✅ 复审通过 |
| IMPL-20-R1 | Aligned Runtime Binding + Fixed Non-Monotonic Overlap + Manifest Schema v2 | 修复 aligned chunk_size 语义漂移（v1 冻结不变量 chunk_size==effective_embedding_max_seq_length，256/512 组合 resolver/Config fail-fast）；Pipeline Counter.model_input_budget 来源改为 config.chunk_size；prepare 增加 counter.tokenizer is pipeline.embedding.get_runtime_tokenizer() 对象同一性硬校验（同 contract 异对象反例测试通过）；FixedSizeChunker overlap 改用 Counter.substring_start（非单调正确，cl100k 语义不变，Fixed 非单调测试证明最左合法 start）；Recursive oversized 判定 max_substring 限定 end（有界扫描回归测试）；MANIFEST_SCHEMA_VERSION=2（runner 使用唯一常量，历史 v1 Artifact 不动）；真实 Corpus chunk-only smoke：37 files / 215 chunks / max content 510 / max model-input 512 / would-truncate 0 / 全部 exact substring | ✅ 复审通过 |
| ABL-21 | BGE-Aligned Chunk Budget Formal Retrieval Ablation | 三套正式 aligned 实验（Dense 04fc6d2111a6、BM25 b35b1102197e、Hybrid e680cdf278b2，Manifest v2，would-truncate=0，max model-input=512，corpus fp=d39634c168e74677）；Dense Hit 0.88→0.84、BM25 0.98→0.98、Hybrid 0.92→0.96（Recall 0.8933→0.9333）；rescue/loss：Dense 1/3、BM25 0/0、Hybrid 2/0（q039/q047）；因果解释见 ABL-21-R1，最终冻结为 strategy-dependent pattern / mechanism attribution insufficient；报告/JSON/study-note 59（见 docs/experiments/agent_ai_v1_tokenizer_aligned_ablation.*） | ✅ 复审通过 |
| ABL-21-R1 | BM25 Control 因果口径 + Non-Monotonic Evidence 修正 | 纯文档/JSON interpretation 修正：BM25 aggregate Gold metrics 较稳定但其 document ranking 36/50 变化 → 不再写"BM25 基本不变→chunk-boundary/lexical 机制较弱→支持 embedding-input alignment 是重要机制"；保守结论改为 strategy-dependent pattern、mechanism attribution insufficient；q039/q047 fusion 解释开放（mechanism currently unresolved，不跑 channel diagnostic）；59 号笔记 509→513→510 明确为 synthetic regression（理论风险/构造反例/真实 BGE 未声称观测三层）；BM25 面试问答同步；正式指标与 Case-level 数字零改动 | ✅ 复审通过 |
| CLOSE-22 | Gate 2 Final Review / Evidence Synthesis / Benchmark Freeze | 新增 gate2_final_review.md（问题→证据→结论→边界组织）、gate2_freeze.json（确定性冻结：IDs/metrics/结论索引）、study-note 60（零基础评测方法）；冻结 Benchmark v1（870e5864df67 / 18c1c0470652，50 case / 58 obligations）；Benchmark winner=Recursive+BM25+cl100k（dbc497c796d5）；Gate 3 primary reference=dbc497c796d5、Hybrid reference=3c613202e1ed；C1-C5 + tokenizer 三层结论；7 个 frozen failure cases；HANDOFF 指向 Gate 3 但未开始 | 🔧 完成，待复审 |
| CLOSE-22-R1 | Gate 2 Freeze Final Evidence-Scope Cleanup | 纯文档/JSON 口径收口：C1 限定为 canonical Recursive+cl100k 三策略对照（Fixed+cl100k Hybrid nDCG 0.791469 > BM25 0.789203，不作全局规律）；Study Note 60 BM25 control 面试回答删除"稳定→变化主要在 Dense 路径"推断，改为 performance impact strategy-dependent；因果教学拆分 retrieval-level causal effect（controlled intervention + document-level Gold 可测）与 evidence/chunk-level attribution（需 chunk-level Gold/evidence-span）；status 清除过期 M4 阶段描述与 ABL-21 旧因果结论；freeze status 保持 pending final closure review；零 Python/零 experiments 修改 | 🔧 完成，待复审 |
| Gate1 | RRF 给缺席通道虚拟排名，单通道文档获得另一通道正分 | 未命中通道贡献严格为 0（见 study-notes 43） | ✅ 复审通过 |
| G1-META-02 | Sparse-only 结果丢失原始元数据 | BM25 存元数据副本，sparse-only 命中恢复（实时入库同步） | ✅ 复审通过 |
| G1-CTX-03A/R1 | 双模块各自截断、预算可加性假设 | 统一渲染契约 + 按最终渲染字符串真实 count 预算 | ✅ 复审通过 |
| G1-CTX-03B | Context 预算未含固定成本与输出预留 | 端到端 Prompt Budget（4096/800/16） | ✅ 复审通过 |
| G1-RANK-04 | assembler 重排覆盖 RRF/MMR 顺序 | 保持上游顺序 + display_score 统一展示分 | ✅ 复审通过 |
| G1-CHUNK-05A/R1 | 普通语义段换块无 overlap；纯分隔符文本崩溃 | 换块回退真实 overlap + _split_text flush pending | ✅ 复审通过 |
| G1-CHUNK-05B | SemanticChunker 会产出不可信结果 | 标记实验性，ExperimentConfig 拒绝，保留手动入口 | ✅ 复审通过 |
| G1-CLOSE-06 | — | Gate 1 文档状态收尾 | ✅ 完成 |

## Chunker 策略状态（G1-CHUNK-05B）

| 策略 | 状态 | 说明 |
|------|------|------|
| fixed | ✅ stable baseline | 可进入正式实验（ExperimentConfig） |
| recursive | ✅ stable baseline | 可进入正式实验（ExperimentConfig） |
| semantic | ⚠️ experimental | 保留手动学习/调试入口；未满足原文 Span/严格预算/Embedding 对齐契约；不得用于正式 Gate 2 基线报告；ExperimentConfig 已拒绝 |

## 测试

- 命令：`python -m pytest --basetemp=.tmp_pytest`（Windows 中文用户名环境规避）
- 历史：130（08-03）→ 139（P0）→ 141（REWORK-01）→ 147（REWORK-02）→ 157（REWORK-03）→ 163（REWORK-03-R1）→ 169（REWORK-03-R2）→ 170（E-01）→ 172（E-02）→ 173（E-03）→ 180（E-04）→ 199（ER-01）→ 213（ER-01 类型契约）→ 227（ER-02）→ 228（ER-02 路径逃逸）→ 242（ER-03）→ 254（ER-04）→ 256（ER-04 序列化）→ 260（Gate1 RRF）→ 266（G1-META-02）→ 269（G1-META-02-R1）→ 277（G1-CTX-03A）→ 280（G1-CTX-03A-R1）→ 292（G1-CTX-03B）→ 301（G1-RANK-04）→ 306（G1-CHUNK-05A）→ 312（G1-CHUNK-05A-R1）→ 314（G1-CHUNK-05B）→ **314**（G1-CLOSE-06 文档收尾，08-06）→ 332（G2-ER-05，08-06）→ 334（G2-ER-05-R1，08-07）→ 382（G2-EVAL-06，08-07）→ 396（G2-EVAL-06-R1，08-07）→ 435（G2-EVAL-07，08-07）→ 442（G2-EVAL-07-R1，08-07）→ 479（G2-EVAL-08，08-07）→ 488（G2-EVAL-08-R1，08-07）→ 522（G2-EVAL-09，08-07）→ 526（G2-EVAL-09-R1，08-07）→ 537（G2-EXP-10，08-07）→ 540（G2-REAL-11 CLI 与全量，08-07）→ 559（G2-REAL-11-R1，08-07）→ 574（G2-DIAG-13，08-08）→ 590（G2-DIAG-13-R1，08-08）→ 595（G2-ANALYSIS-14，08-08）→ 604（G2-ABL-15，08-08）→ 610（G2-ABL-16，08-08）→ 624（G2-ABL-16-R1，08-08）→ **625（G2-ABL-17，08-08）** → **635（G2-DIAG-18，08-08）** → **639（G2-DIAG-18-R1，08-08）** → **642（G2-DIAG-18-R2，08-08）** → **668（G2-IMPL-20，08-08）** → **673（G2-IMPL-20-R1，08-08）**

## Git

- 远端：GitHub `wgqa/my_agent`，分支 main
- 最近验收基线：REWORK-P0-01/02/03 + E-01~E-04 + ER-01~ER-04 复审通过；**Gate 1（基础 RAG 可信状态）全部任务复审通过，正式通过**（含 G1-META-02、G1-CTX-03A/R1/03B、G1-RANK-04、G1-CHUNK-05A/R1/05B；具体 hash 以 git log 为准，本文件不维护提交哈希）

## 文档地图

| 文件 | 用途 |
|------|------|
| README.md | 快速上手（安装/配置/API） |
| docs/baseline.md | M0 工程基线 |
| docs/known-issues.md | 已知问题（仅剩增强级 Bug 15） |
| docs/study-notes/ | 学习笔记 00-60 |
| docs/design/ | 设计文档（tokenizer-aligned chunk intervention 契约等） |
| docs/archive/ | 历史大规划（改进路线图 / RAG 与 Agent 融合），备查不跟进 |
| ../docs/superpowers/ | 原始设计与实施计划 |
