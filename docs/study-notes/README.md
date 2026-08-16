# 学习笔记索引（docs/study-notes/）

> **顶部声明**：本文件是 `docs/study-notes/` 全部学习笔记的索引。每份笔记**只出现一次**，按状态分为四类：`CURRENT` / `FROZEN_EVIDENCE` / `SUPERSEDED` / `HISTORY`。本索引只做索引，**不修改任何原始笔记**。

**分类规则**

- `CURRENT`：描述当前仍适用的契约、状态、基础设施或方法论，直接指导后续任务。
- `FROZEN_EVIDENCE`：记录已冻结实验/评测证据（Gate 2 与 Gate 3）；其中数字分别以 `docs/experiments/gate2_freeze.json` 与 `docs/experiments/gate3_holdout_final.json` 为权威来源，本类笔记是证据链与学习参考，不是可更新的现状文档。
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

## CURRENT（44 份）

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
| 61 | [61-API上传安全边界.md](61-API上传安全边界.md) | API 上传安全边界（安全文件名 / 唯一临时目录 / 分块读取 / 20 MiB 上限 / 通用错误响应） |
| 62 | [62-API本地暴露与请求边界.md](62-API本地暴露与请求边界.md) | API 本地暴露与请求边界（CORS 白名单 / 127.0.0.1 默认监听 / Query 输入上限 / /query 通用错误响应） |
| 63 | [63-Gate3问题分解与自适应检索设计.md](63-Gate3问题分解与自适应检索设计.md) | Gate 3 问题分解与自适应检索设计契约（G3-DESIGN-01，主设计文档与 ADR-001 的索引） |
| 64 | [64-Gate3Case与评测集身份.md](64-Gate3Case与评测集身份.md) | G3-DATA-02A：Gate3Case 与 Gate3EvaluationSet 强类型契约（数据 Schema 基础设施；36 条问题与 sealed holdout 尚未创建） |
| 65 | [65-Gate3数据集划分、Holdout封存与泄漏防护.md](65-Gate3数据集划分、Holdout封存与泄漏防护.md) | G3-DATA-02C：24/12 分层划分、Holdout 封存与泄漏防护（Goodhart/数据泄漏/预注册 split/语义身份 vs 字节身份/canonicalization/sealed 流程；不含 Holdout case_id 或题目） |
| 66 | [66-Gate3-QueryPlan强类型契约.md](66-Gate3-QueryPlan强类型契约.md) | G3-PLAN-03：QueryPlan/Subquery 强类型契约（frozen dataclass、字段级校验、跨字段不变量、plan_id、fallback factory；只做 Schema，不含 Planner/Router/Evidence） |
| 67 | [67-Gate3有界Planner输出解析与Fallback.md](67-Gate3有界Planner输出解析与Fallback.md) | G3-DECOMP-04A：Planner 抽象接口、严格 JSON 解析、错误分类与统一 fallback（BaseQueryPlanner/PlannerOutcome/parse_planner_output；未接真实 LLM） |
| 68 | [68-Gate3真实Planner调用、Prompt版本与超时回退.md](68-Gate3真实Planner调用、Prompt版本与超时回退.md) | G3-DECOMP-04B-01：正式 Planner Prompt v1、OpenAI-compatible Provider、单次调用边界、超时/Provider 错误回退、PlannerCallMetadata（只经 Fake Client 验证，未调真实模型） |
| 69 | [69-Gate3-Planner-Dev真实调用与校准评测.md](69-Gate3-Planner-Dev真实调用与校准评测.md) | G3-DECOMP-04B-02A：公开 Dev 24 Case 真实 DeepSeek baseline（run_id 497808269bdd）、可复现校准 Runner、Planning 指标与人工语义审查（调优前快照，未改 Prompt） |
| 70 | [70-Gate3最小Agent-Runtime与执行轨迹.md](70-Gate3最小Agent-Runtime与执行轨迹.md) | G3-RUNTIME-05A：最小离线 Agent Runtime（RouteDecision/EvidenceBundle/VerificationResult/RunTrace + AgentRuntime，direct/single 执行、decomposed 只路由、预算/异常/脱敏 Trace） |
| 71 | [71-Gate3-Agent-Runtime接入Pipeline与API.md](71-Gate3-Agent-Runtime接入Pipeline与API.md) | G3-RUNTIME-05B：PipelineRetrievalAdapter/AnswerAdapter + build_pipeline_agent_runtime + POST /agent/query（BM25-only retrieve_sparse、grounded Citation 校验、direct 单次生成、decomposed 仍 deferred） |
| 72 | [72-Gate3多问题检索与证据轮转合并.md](72-Gate3多问题检索与证据轮转合并.md) | G3-RUNTIME-05C：decomposed 真多子问题 BM25 执行 + subquery_round_robin_v1 证据合并 + required-subquery 覆盖检查（INCOMPLETE_SUBQUERY_EVIDENCE 拒答、evidence_merged Trace、API sources 含 query_id） |
| 73 | [73-Gate3自适应检索、单次补检索与证据验证.md](73-Gate3自适应检索、单次补检索与证据验证.md) | G3-ADAPT-06A：确定性 Adaptive Policy v1（BM25/Hybrid 策略表 + 固定原因码）、RouteDecision v2、最多一次 Hybrid Evidence Rescue、Verifier v2 coverage、API sources 契约修正 |
| 74 | [74-Gate3自适应检索Dev对照实验.md](74-Gate3自适应检索Dev对照实验.md) | G3-ADAPT-06B：Dev 24 真实四组检索对照（A 原问题BM25/B 原问题Hybrid/C Plan+BM25/D Plan+Adaptive），run_id 4d29b9e0b2cc；结果为负（C/D 覆盖 0.727 < A 0.818、调用 49 vs 24、C==D） |
| 75 | [75-Gate3子查询RRF合并实验.md](75-Gate3子查询RRF合并实验.md) | G3-ADAPT-06C-MERGE：round-robin v1 → subquery_rrf_merge_v2 单变量 merge 实验，run_id 57811e77ecfa；C/D final obligation 32/44→37/44、merge-drop 5→0、调用不变、零回归（正结果） |
| 76 | [76-Gate3真实E2E答案与引用评测.md](76-Gate3真实E2E答案与引用评测.md) | G3-E2E-07A：Dev 24 真实 Planner+Generator 端到端答案评测（两阶段 Gold 隔离 + LLM Judge），run_id 4172f6cc1d6f；answer_pass 8/20、answer_obligation 21/44、4 case generator 空输出失败 |
| 77 | [77-Gate3系统冻结与Holdout前置审计.md](77-Gate3系统冻结与Holdout前置审计.md) | G3-FREEZE-08-SYSTEM：Gate 3 Dev 侧系统 Freeze Candidate（gate3_system_freeze_id=2ec11a69b173、frozen baseline fed9d15）；机器可核验 freeze JSON、known_limitations、holdout_execution_contract（Holdout=BLOCKED）；面向面试复习 |
| 78 | [78-Gate3-Holdout一次性执行协议.md](78-Gate3-Holdout一次性执行协议.md) | G3-HOLDOUT-09A-HARNESS：一次性 Freeze-bound Holdout harness（独立 Gate3HoldoutConfig、freeze 唯一配置来源、无 CLI override、attempt ledger、preflight 0 LLM/sealed）；holdout_run_id a1dc0a4bab03 |
| 79 | [79-Gate3-Holdout最终执行器与封卷流程.md](79-Gate3-Holdout最终执行器与封卷流程.md) | G3-HOLDOUT-09B-FINAL-EXECUTOR + R1-REAL-WIRING：execute_holdout 写死 09C 顺序 + sealed 边界 + formal identity（含 holdout_jsonl_sha256）；attempt prepared→running→completed；系统失败 vs 基础设施失败；synthetic 验证；R1 把 read_real_sealed_inputs / run_holdout_generation / run_holdout_evaluation 接到真实 frozen E2E pipeline、formal provenance binding 与 ledger formal-identity 绑定、CLI --execute 真实 wiring（只差 09C 授权） |
| 81 | [81-Gate4结构化ToolAgent设计与执行模型.md](81-Gate4结构化ToolAgent设计与执行模型.md) | G4-DESIGN-01：Gate 4 Structured Tool Agent 设计契约的面向学习讲解（Gate3 vs Gate4 / Tool / Structured Tool Call / ToolSpec / ToolCall / Observation / 为什么不让 LLM 直接执行 / Registry 与 Executor 分层 / Bounded Loop / Tool error vs Agent failure / Observation 反哺决策 / Trace vs CoT / 首批 3 个只读工具 / multi-tool 示例 / 常见错误 / 面试问答 / 代码阅读路线）；Gate 4 = IN PROGRESS，0 Tool 实现 |
| 82 | [82-Gate4-ToolRegistry与安全执行器.md](82-Gate4-ToolRegistry与安全执行器.md) | G4-TOOL-02：Structured Tool Agent 纯确定性底座（ToolSpec/ToolCall/ToolObservation/ToolHandler/RegisteredTool/ToolRegistry/ToolExecutor + JSON 安全 + fail-fast/fail-closed + Fake Handler 测试基础设施）；50 测试；G4-TOOL-02 = REVIEW PENDING（Structured Tool core implemented candidate，仍 0 real tools / 0 LLM selection / 0 tool loop） |
| 83 | [83-Gate4三个真实Tool与Adapter设计.md](83-Gate4三个真实Tool与Adapter设计.md) | G4-TOOLS-03：三个真实 read-only Tool（calculator AST 白名单求值 / code_search filesystem sandbox / knowledge_search 复用 RetrievalPort）接入统一 Tool core；capability adapter、模型不能控 top_k/strategy、literal vs regex、output 受限、异构 Tool 统一契约；41 测试；G4-TOOLS-03 = REVIEW PENDING（3 个真实 read-only Structured Tools implemented candidate） |
| 84 | [84-Gate4结构化Tool选择与LLM决策边界.md](84-Gate4结构化Tool选择与LLM决策边界.md) | G4-AGENT-04：LLM 单步结构化 Decision（AgentAction 强判别联合、ToolCallAction≠ToolCall、call_id 系统生成、strict JSON/duplicate key/unknown field、Tool allowlist、Decision+Executor 双重 schema 校验、Prompt 软约束 vs Parser/Registry 硬约束、fail closed vs fallback、Provider metadata、不记录 CoT、Prompt SHA、Fake Client、单步 vs Loop）；45 测试；G4-AGENT-04 = REVIEW PENDING（LLM single-step structured decision candidate） |
| 85 | [85-Gate4有界Tool-Agent-Loop与Observation反馈.md](85-Gate4有界Tool-Agent-Loop与Observation反馈.md) | G4-RUNTIME-05：Decision→Action→Observation→Decision 有界循环（预算 5/4/2、最后 iteration 不再执行 Tool、duplicate ToolCall 去重、Tool error 可恢复但 2 次封顶、不自动重试、Observation 不可信数据、Trace≠CoT、Scripted/Fake LLM + 三个真实 Tool 集成测试）；16 测试；G4-RUNTIME-05 + R1 = Reviewer accepted / CLOSED（bounded Structured Tool Agent Loop implemented） |
| 86 | [86-Gate4-Tool-Agent评测协议与Gold设计.md](86-Gate4-Tool-Agent评测协议与Gold设计.md) | G4-EVAL-06A：Tool-Agent 评测协议与 Gold 设计（为什么不能只测最终答案 / first action vs first tool / required tool coverage / 不要唯一 Gold sequence / unnecessary & forbidden tool / termination / Parser failure≠安全拒绝 / Dev vs Holdout / 为什么先 public Dev / deterministic assertion vs LLM-as-Judge / benchmark identity SHA / 先冻结尺子再跑模型 / 防止看结果改 Gold；24 Case 六类各 4，knowledge_search Gold 绑定公开语料）；G4-EVAL-06A = REVIEW PENDING |
| 87 | [87-Gate4正式Tool-Agent评测Runner与Gold隔离.md](87-Gate4正式Tool-Agent评测Runner与Gold隔离.md) | G4-EVAL-06B-01 + R1：正式 Runner（两阶段 Gold 隔离 / 四层 run 身份 / preflight gates / micro coverage / 15 项冻结指标 numerator/denominator/value / safe Provider metadata / artifact manifest / 原子 finalize / 0-LLM harness 验证评测状态机）；R1 修正 Provider wiring（base_url=FROZEN_BASE_URL）/RunConfig 冻结/duplicate & task_completion 指标/ExecutionCase 隔离/metadata 一致性/token 全有才求和/containment；Fake/Scripted Provider + real Tool + real corpus preflight，0 real LLM；G4-EVAL-06B-01/R1 = Reviewer accepted / CLOSED |
| 88 | [88-Gate4第一次正式Tool-Agent-Dev基线与错误分析.md](88-Gate4第一次正式Tool-Agent-Dev基线与错误分析.md) | G4-EVAL-06B-02：第一次真实 DeepSeek Tool-Agent Dev baseline（run_id fa4ab9aa5f13，41 次决策调用）；为什么 Tool-Agent 不能只看最终答案 / first action vs first tool vs required coverage / multi-step sequence 怎么看 / refusal reason 单独衡量 / parse failure vs 安全 refusal / budget stop vs duplicate stop / token-latency 解读 / public Dev baseline 不是 Holdout / baseline 差不能现场调参；headline：task_completion 20/24、required_coverage 0.7、allowed_sequence_match 1/4 |
| 89 | [89-Gate4-Structured-Tool-Agent-API与安全Trace.md](89-Gate4-Structured-Tool-Agent-API与安全Trace.md) | G4-E2E-07A：Structured Tool-Agent API（POST /tool-agent/query，独立于 Gate 3 /agent/query）；为什么不能共用 runtime 全局 / API 不开放 budget-provider-allowlist / HTTP transport error vs Agent structured failure / refused-parse-budget 仍 200 / safe trace≠CoT / Tool Observation 是 untrusted / Fake Provider+Real Tool E2E 集成测试价值 / baseline 后先接 API 不马上调 Prompt；core/tool_agent/integration.py + api/schemas.py + api/app.py _safe_trace；15 API 测试；G4-E2E-07A = Reviewer accepted / CLOSED |
| 90 | [90-Gate4真实HTTP多工具E2E-Smoke.md](90-Gate4真实HTTP多工具E2E-Smoke.md) | G4-E2E-07B：真实 HTTP 多工具 E2E smoke（非 benchmark、无 Gold）；FastAPI lifespan → production ToolAgentRuntime → deepseek-chat → real Tool → Observation → 后续 Decision → safe Trace；6 条固定 smoke 全 HTTP 200 结构化（direct/calculator/code_search/knowledge_search/multi-tool code→calc/safety refuse）；trace 白名单 + 0 key/raw/CoT/prompt/traceback；G4-E2E-07B = COMPLETED / REVIEW PENDING |

## FROZEN_EVIDENCE（11 份）

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
| 80 | [80-Gate3最终Holdout与Gate3封卷复盘.md](80-Gate3最终Holdout与Gate3封卷复盘.md) | G3-CLOSE-10-HOLDOUT-OFFLINE-SEAL：记录的是 **Gate 3 冻结结论**（唯一一次正式 Holdout formal_holdout_run_id=cb157fd3837f 与封卷复盘，含 attempt 41c991a839cb 永久保留、replacement 5f5f0c7bef9b）；数字以 `docs/experiments/gate3_holdout_final.json` 为权威来源 |

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

- 编号覆盖 00–90 共 **91 份**，每份只出现一次：CURRENT 44 + FROZEN_EVIDENCE 11 + SUPERSEDED 1 + HISTORY 35 = 91。
- 原始笔记一律未修改。
- 当前日期：2026-08-16。
