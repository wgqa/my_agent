# 可评测 RAG Agent 项目主路线图 v4

> 项目：wgqa/my_agent<br>
> 版本：v4<br>
> 更新日期：2026-08-15<br>
> 审计基线：c2cf0d724d5ade31a4bac9b504c6897480d3df95<br>
> 基线提交：docs: close Gate 3 after final holdout seal<br>
> 项目目标：面向大厂校招，完成一个正确、可评测、可复现、可解释、可展示的 RAG Agent 项目

---

# 0. 一页结论

项目已经不再是普通的 RAG 学习 Demo。

当前真实状态是：

| 阶段 | 状态 | 结论 |
|---|---|---|
| Gate 1：基础 RAG 正确性 | CLOSED | 核心数据、分块、检索、上下文和引用契约已经过系统修复 |
| Gate 2：检索评测与消融 | CLOSED / FROZEN | 已形成可复现、可审计、可冻结的检索实验体系 |
| Gate 3：Query Decomposition + Adaptive Retrieval | CLOSED / FROZEN | 系统/数据/唯一一次 formal Holdout 已冻结封档，冻结成绩不再重写 |
| Gate 4：结构化 Tool Agent | CLOSE CANDIDATE / pending Reviewer | 强类型 Structured Tool Agent + 3 只读 Tool + 5/4/2 bounded loop + public Dev benchmark（task completion 20/24）+ real FastAPI/DeepSeek E2E 已完成；gate4_freeze.json 已冻结，最终 CLOSED 待 Reviewer 审核 freeze 后签发（执行 Agent 不自写 CLOSED） |
| Gate 5：端到端评测与工程收口 | NEXT | 尚未开始，不得提前开始 |

### Gate 3 冻结摘要（CLOSED / FROZEN，权威来源 `docs/experiments/gate3_holdout_final.json`）

| 冻结身份 | 值 |
|---|---|
| gate3_system_freeze_id | `2ec11a69b173` |
| gate3_dataset_freeze_id | `257fa0d0a6d6` |
| formal_holdout_run_id | `cb157fd3837f` |
| holdout eval / case_count | `79a6bc0814a3` / 12 |

- Gate 3 已正式 CLOSED / FROZEN（G3-CLOSE-11-FINAL-STATUS 签发）；冻结成绩只读，**不得重新解释或修改**；
- 唯一一次 formal Holdout 已执行并离线封档（attempt 41c991a839cb 永久保留、replacement 5f5f0c7bef9b completed）；聚合结果见 `docs/experiments/gate3_holdout_final.json` 与学习笔记 80；
- 数据构建 Agent 已停止；Gate 3 的 dev 公开 / holdout 私有边界维持不变。

当前项目最强的部分是：

1. 修复过真实的数据正确性与检索正确性问题；
2. 实验身份、语料身份、评测集身份和工作区已经隔离；
3. 保存逐样本结果，不只保存平均分；
4. 对 Dense、BM25、Hybrid、Chunk Strategy 和 Tokenizer Alignment 做过正式实验；
5. 能区分事实、推测和未验证因果；
6. Gate 2 已冻结，不再为了追求更好数字反复调参。

当前项目最主要的不足是（2026-08-15 收敛，完整记录见 §5）：

1. Structured Tool Agent 尚未实现；
2. Generator robustness 仍弱；
3. Retrieval → Answer synthesis gap 明显；
4. claim-level faithfulness 仍未完成；
5. DATA-CONSIST-01 等产品一致性债务（P1，不阻塞 read-only Gate 4 v1）；
6. README / dependency lock / CI / Docker / 公共复现仍需 Gate 5 收口。

（历史弱点见 §5.2「已解决 / 历史」，不再列为当前事实。）

因此下一阶段不是直接堆 Agent 框架，也不是立刻做 GraphRAG，而是：

    文档与安全预检      ✅ 完成
    → 冻结 Gate 3 评测协议和新数据   ✅ 完成
    → Query Decomposition           ✅ 完成
    → Multi-query Retrieval         ✅ 完成
    → Adaptive Retrieval            ✅ 完成
    → 正式对照实验 + formal Holdout  ✅ 完成（Gate 3 = CLOSED / FROZEN）
    → 结构化 Tool Agent             ← 当前（Gate 4 = CLOSE CANDIDATE / pending Reviewer，gate4_freeze.json 已冻结，最终 CLOSED 待 Reviewer 签发）
    → 端到端评测与工程收口          （Gate 5，后续）

---

# 1. 项目定位与边界

## 1.1 项目定位

项目定位保持不变：

> 面向技术文档与代码的可评测 RAG Agent，支持混合检索、多步问题分解、结构化工具调用和可追溯引用。

面试叙事不是“调用了多少框架”，而是：

- 如何保证数据链路正确；
- 如何避免虚假实验；
- 如何用冻结数据和逐样本证据选择检索策略；
- 如何把 RAG 能力演进成受控 Tool；
- 如何限制 Agent 的步骤、成本、权限和错误；
- 如何诚实说明尚未验证的能力。

## 1.2 核心原则

- 正确性优先；
- 实验说话；
- 一次一项；
- Gate 验收；
- 冻结结果不回写；
- 不为热门技术改变主线；
- 不把固定 Workflow 冒充 Agent；
- 不把局部实验结论推广成普遍规律；
- 不过度平台化。

## 1.3 明确不做

Gate 5 之前默认不做：

- 多 Agent；
- Kubernetes；
- Kafka；
- 全量微服务化；
- 完整 IAM；
- 多向量数据库适配；
- 大规模分布式索引；
- 为了简历而重写全部 Python AI 链路；
- 没有失败证据支撑的 GraphRAG。

---

# 2. 真相来源与协作治理

## 2.1 文档优先级

不同信息使用不同真相来源：

| 信息 | 真相来源 |
|---|---|
| 用户是否批准进入下一阶段 | 用户当前决定 |
| 实现是否存在 | 最新代码与测试 |
| Gate 2 冻结数字和结论 | docs/experiments/gate2_freeze.json |
| 当前实时任务 | docs/status.md |
| 长期路线 | 本路线图 |
| 快速交接 | docs/HANDOFF.md |
| 设计演进和学习历史 | docs/study-notes 与 docs/archive |

规则：

- status.md 不得覆盖 freeze JSON 中的冻结事实；
- HANDOFF 只做摘要，不得成为第二份状态表；
- study-notes 可保留历史过程，但必须标记 current、superseded 或 history；
- 路线图不记录每次小修复的流水账；
- 旧路线图进入 archive，不并行维护。

## 2.2 三方分工

| 角色 | 职责 |
|---|---|
| 用户 | 拍板范围、优先级和是否进入下一 Gate |
| 审计与指导模型 | 审计、拆单、给任务卡、独立验收、防路线漂移 |
| 执行 Agent | 按任务卡最小实现、补测试、运行命令、提交并汇报 |

执行纪律：

1. 一次只推进一个任务卡；
2. 未验收不得自行进入下一项；
3. 代码 Bug 先 RED 再 GREEN；
4. 纯文档任务不要求伪造 RED/GREEN；
5. 不删除或弱化测试换取通过；
6. 不顺手重构无关模块；
7. 执行 Agent 的测试汇报必须由审计方独立核对；
8. 用户可随时停止、调整或否决任务。

---

# 3. v2 到 v3 的主要变化

| v2 内容 | v3 处理 |
|---|---|
| Gate 1 仍有退出阻塞 | 更新为 CLOSED |
| Gate 2 仍在建设 ExperimentRunner | 更新为 CLOSED / FROZEN |
| 最近任务从 G1-RRF 开始 | 替换为 Gate 3 preflight 和 Gate 3 设计 |
| M4 评测与消融整体标记完成 | 收紧为“检索评测与消融完成”，端到端生成评测仍未完成 |
| 50 条 QA 被当作长期最终测试集 | 降级为冻结回归基准，并为 Gate 3 新建 sealed holdout |
| Hybrid 被自然视为默认主线 | 以实验证据改为 BM25 primary，Hybrid 作为 control |
| 安全和依赖锁定放在很后面 | 上传安全作为公开运行前 P0，依赖与 CI 在工程收口优先处理 |
| GraphRAG 位于高级 RAG 路线中 | 保留决策 Gate，不自动进入主线 |
| Gate 5 才关注生成评测 | 在 Gate 4 后、公开收口前单独建立端到端评测 |
| 旧学习笔记全部视为当前说明 | 增加 current、superseded、history 索引要求 |

---

# 4. Gate 1 与 Gate 2 冻结快照

## 4.1 Gate 1：CLOSED

Gate 1 已完成：

- Loader、Chunker、Embedding、VectorStore、Retriever、Reranker、Generator 基础链路；
- Hybrid Candidate → RRF → Rerank → Final 语义修复；
- BM25 upsert、统计膨胀和 ID/正文错位修复；
- TokenCounter 与 Chunker 静默丢字修复；
- RRF 缺席通道计分与确定性 tie-break；
- Sparse-only 元数据完整性；
- ContextAssembler 统一上下文预算；
- 引用、拒答和生成异常基础处理；
- 实验配置、工作区、语料身份等 Gate 2 前置能力。

Gate 1 不重新打开。发现历史 Bug 时新增回归任务，不回滚 CLOSED 状态。

## 4.2 Gate 2：CLOSED / FROZEN

冻结身份：

| 项目 | 值 |
|---|---|
| corpus_id | 870e5864df67 |
| evaluation_set_id | 18c1c0470652 |
| 文档数 | 37 |
| Case 数 | 50 |
| 单文档 Case | 43 |
| 多文档 Case | 7 |
| Gold document obligations | 58 |
| Top K | 5 |

冻结 Primary：

| 字段 | 值 |
|---|---|
| 组合 | Recursive + BM25 + cl100k_content_v1 |
| experiment_id | dbc497c796d5 |
| result_id | acd92171966d |
| Hit@5 | 0.98 |
| Recall@5 | 0.953333 |
| MRR | 0.787333 |
| nDCG@5 | 0.820643 |

冻结 Hybrid Control：

| 字段 | 值 |
|---|---|
| 组合 | Recursive + Hybrid + cl100k_content_v1 |
| experiment_id | 3c613202e1ed |
| result_id | e27141a2b63e |
| Hit@5 | 0.92 |
| Recall@5 | 0.893333 |
| MRR | 0.786667 |
| nDCG@5 | 0.799360 |

## 4.3 九组正式实验

| Chunk / Policy | Retriever | Hit@5 | Recall@5 | MRR | nDCG@5 |
|---|---:|---:|---:|---:|---:|
| Recursive / cl100k | Dense | 0.88 | 0.863333 | 0.748333 | 0.762381 |
| Recursive / cl100k | BM25 | 0.98 | 0.953333 | 0.787333 | 0.820643 |
| Recursive / cl100k | Hybrid | 0.92 | 0.893333 | 0.786667 | 0.799360 |
| Fixed / cl100k | Dense | 0.80 | 0.786667 | 0.671667 | 0.689649 |
| Fixed / cl100k | BM25 | 0.96 | 0.933333 | 0.758333 | 0.789203 |
| Fixed / cl100k | Hybrid | 0.92 | 0.913333 | 0.760000 | 0.791469 |
| Recursive / BGE aligned | Dense | 0.84 | 0.840000 | 0.669667 | 0.707847 |
| Recursive / BGE aligned | BM25 | 0.98 | 0.943333 | 0.785000 | 0.806386 |
| Recursive / BGE aligned | Hybrid | 0.96 | 0.933333 | 0.763333 | 0.795896 |

这些数字只适用于：

- 当前 37 份语料；
- 当前 50 条 Gold；
- Top-5 Chunk Retrieval；
- 文档级 first-hit dedup 排名；
- 当前模型、配置和实现。

不得写成“BM25 永远优于 Hybrid”或“Tokenizer 对齐一定提升效果”。

## 4.4 已确认结论

- canonical Recursive + cl100k 三策略对照中，BM25 在 Hit、Recall 和 nDCG 上最好；
- Recursive 在当前基准上整体优于 Fixed；
- RRF 必须使用确定性排序：rrf_score 降序，再按 chunk_id 升序；
- 声明的 Retriever 策略必须与运行时真实类型绑定；
- Hybrid 和 BM25 实验必须校验 sparse_count、vector_count 和 total_chunks；
- Dense 与 BM25 的 offline/formal 结果已达到逐 Case、逐 Chunk 一致；
- cl100k 预算与 BGE runtime tokenizer 存在 Level 1 mismatch；
- Recursive cl100k 的 57/215 Chunk 在实际 BGE runtime 下会截断；
- aligned intervention 将 would-truncate 从 57/215 降为 0/215；
- 对齐干预的效果依赖策略：Dense 下降、BM25 汇总接近、Hybrid Recall 提升；
- 多文档召回不完整是真实失败类型。

## 4.5 尚未证明的因果

- 某个具体 Chunk 边界直接导致失败；
- BGE 截断直接导致某条检索失败；
- aligned 策略的变化主要由 Tokenizer 对齐造成；
- q039、q047 的 Hybrid rescue 具体来自哪种融合机制；
- Query Decomposition 一定能修复多文档召回。

这些问题可以成为后续实验假设，但不能作为既定事实。

## 4.6 冻结回归 Case

BM25 primary：

- q013：Hit failure；
- q031：多文档 Recall 0.5；
- q036：多文档 Recall 0.666667；
- q038：多文档 Recall 0.5。

Hybrid control：

- q019：Hybrid Hit failure，但 BM25-only 命中；
- q034：Hybrid Recall 0.5，但 BM25 primary Recall 1.0；
- q039：Hybrid Hit failure，aligned Hybrid rescue，机制未决；
- q047：Hybrid Hit failure，aligned Hybrid rescue，机制未决。

交集：

- q031；
- q036。

以上 Case 用于回归和失败分析，不得通过删除、改 Gold 或针对性硬编码来“修复”。

---

# 5. 当前缺点与优先级

以下只列当前影响项目质量和校招叙事的主要问题，不做无意义挑刺。

## 5.1 当前主要不足（2026-08-15 收敛）

1. **Structured Tool Agent 尚未实现**：Gate 3 已具备 RAG-specific Agent Runtime（检索 / 生成端口 + 有界执行 + 脱敏 RunTrace），但 Gate 4 的预注册 Tool 集合、结构化 Tool Selection、Bounded Tool Loop 仍为设计阶段（G4-DESIGN-01 / R1）。不得在简历或 README 中声称已实现 Tool Agent；
2. **Generator robustness 仍弱**：formal Holdout 中 4/12 case 因 generator 空输出而失败（系统行为性失败计入正式结果），复杂上下文下生成稳定性是当前最弱环节；
3. **Retrieval → Answer synthesis gap 明显**：Holdout 检索 obligation 18/21=0.857，但 answer_obligation 8/21=0.381、answer_pass 4/10=0.4，检索证据到最终答案正确性之间存在明显落差；
4. **claim-level faithfulness 仍未完成**：当前为 query-level obligation coverage + LLM Judge 辅助评测，尚未做 claim-level entailment / faithfulness 的系统评测；
5. **DATA-CONSIST-01 等产品一致性债务**：删除一致性、文档身份、API Citation 契约仍待收口。定位 = **P1 debt**，不阻塞 read-only Gate 4 v1；在引入 state-mutating Tool 或 public release 前必须重新审查（见 §5.3）；
6. **README / dependency lock / CI / Docker / 公共复现仍需 Gate 5 收口**：lockfile、CI、Docker、可公开最小语料与单命令复现均未完成，README 仍落后于内部能力。

## 5.2 已解决 / 历史（不再作为当前缺点）

以下问题已解决或已被后续阶段取代，保留为历史记录，不再列入当前缺点。

- **P0-1 上传边界不安全 → RESOLVED（SEC-P0-01A，2026-08-09）**：安全文件名白名单、独立临时目录、1 MiB 分块、20 MiB 上限、通用错误响应；
- **P0-1B API 暴露与请求边界 → RESOLVED（SEC-P0-01B，2026-08-09）**：CORS 白名单、默认 127.0.0.1、Query 输入上限、通用错误响应；
- **P0-2 Gate 3 数据泄漏风险 → RESOLVED（G3-DATA-02，2026-08-13）**：36 条问题已封存，24/12 dev/holdout 分层隔离，sealed holdout 私有边界维持（dataset freeze `257fa0d0a6d6`）；
- **P1-1 还没有 Agent → 已被 Gate 3 取代**：Gate 3 已具备 RAG-specific Agent Runtime（RouteDecision / EvidenceBundle / Verifier / RunTrace、`/agent/query`、预算与异常结构化失败、脱敏 Trace）。当前准确表述改为 §5.1-1"Structured Tool Agent 尚未实现"；
- **P1-2 评测范围仍不完整 → 部分保留**：retrieval-level（Gate 2）与 answer/citation（Gate 3 Dev-only + formal Holdout）已闭环；仍缺 claim-level faithfulness、端到端 P50/P95 与成本评测（见 §5.1-4 与 Gate 5）；
- **P1-3 Gate 3 复杂问题样本不足 → RESOLVED（G3-DATA-02）**：当时仅 7 条多文档 Case，现已建成 36 条复杂问题（comparison / multi_entity / causal / troubleshooting 等）并分层封存；
- **无结构化 Trace → RESOLVED（G3-RUNTIME-05A/05B/05C）**：Gate 3 已引入 RunTrace（事件化、脱敏，禁 Key / traceback / 正文）；
- **P1-4 公开可复现性不足 → 保留为当前不足 §5.1-6**；
- **P1-5 README 严重落后 → 保留为当前不足 §5.1-6**（README 应更新为：Gate 3 已冻结、Gate 4 设计契约已冻结但 Tool Agent 未实现）；
- **P1-6 产品数据一致性仍有风险 → 保留为当前不足 §5.1-5**（DATA-CONSIST-01）；
- **P1-7 API 丢失引用契约 → 保留为当前不足 §5.1-5**（DATA-CONSIST-01 组成部分）。

## 5.3 DATA-CONSIST-01 定位（P1 debt）

- **状态**：P1 debt；
- **不阻塞**：read-only Gate 4 v1（knowledge_search / code_search / calculator 均为只读，不依赖写路径一致性）；
- **重新审查触发点**：引入 state-mutating Tool（任何写操作工具）或 public release 之前，必须先完成并重新审查 DATA-CONSIST-01；
- **组成**：原 P1-6（删除一致性 / 文档身份）与 P1-7（API Citation 契约）。

## 5.4 保留的工程待办（P2，Gate 5 收口）

- 无 pyproject.toml；
- 无 uv.lock 或其他 lockfile；
- 无 GitHub Actions；
- 无 Docker；
- 无 SSE 结构化事件；
- 无请求 ID；
- 无统一错误码；
- 无正式性能报告；
- ExperimentRunner 已较大，Gate 4 不应继续把 Tool Agent 逻辑堆入 Runner；
- legacy Evaluator 与正式 ExperimentRunner 并存，职责边界需在后续整理；
- 部分早期学习笔记描述已过时，缺少 current、superseded、history 索引。

这些不需要现在全部返工，但必须有明确进入时机（Gate 5）。

---

# 6. 从现在开始的唯一任务序列

除 P0 Bug 外，不并行跨项。

| 顺序 | 任务 | 目标 | 状态 |
|---:|---|---|---|
| 1 | DOC-HOUSEKEEP-01 | 修正文档陈旧状态，不重开 Gate 2 | CLOSED |
| 2 | SEC-P0-01 | 收紧 API 上传和默认暴露边界 | CLOSED |
| 3 | G3-DESIGN-01 | 冻结 Gate 3 问题、Baseline、Schema、指标和停止条件 | CLOSED |
| 4 | G3-DATA-02 | 建立复杂问题开发集与 sealed holdout | CLOSED / SEALED |
| 5 | G3-PLAN-03 | 问题类型与 QueryPlan 结构化契约 | CLOSED |
| 6 | G3-DECOMP-04 | 有界问题分解与失败回退 | CLOSED |
| 7 | G3-MRETR-05 | Multi-query Retrieval 与证据映射 | CLOSED（并入 G3-RUNTIME-05） |
| 8 | G3-ADAPT-06 | 可解释 Adaptive Router | CLOSED |
| 9 | G3-CORRECT-07 | 仅在证据支持时加入一次有限补检索 | CLOSED（以 G3-ADAPT-06A 单次 Evidence Rescue 收敛） |
| 10 | G3-EVAL-08 | Dev 调整、冻结实现、sealed holdout 正式评测 | CLOSED（G3-E2E-07A 等） |
| 11 | G3-CLOSE-09 | 失败分析、结论边界、冻结 Gate 3 | CLOSED（G3-CLOSE-10/11） |
| 12 | DATA-CONSIST-01 | 删除一致性、文档身份、API Citation 契约 | P1（Gate 4 期间可选前置，非阻塞） |
| 13 | Gate 4 | 结构化 Tool Agent（冻结阶段路线见 §9.8） | READY / NEXT |
| 14 | Gate 5 | 端到端评测与工程收口 | NOT STARTED / PARTIAL INFRASTRUCTURE |

工作单元定义：

> 1 个工作单元 = 2～4 小时专注开发、测试、复审和学习。

DOC-HOUSEKEEP-01 是纯文档清理，不修改冻结 JSON，不重新运行 Gate 2 实验。

SEC-P0-01 是安全插单。完成前不要将当前 API 暴露到公网。

Gate 3 已 CLOSED / FROZEN，其上冻结数字只读，不再为追求更好数字反复调参。

---

# 7. Gate 3：Query Decomposition + Adaptive Retrieval

> 本历史章节保留 Gate 3 的设计要求与实施路径。当前 Gate 3 = **CLOSED / FROZEN**：冻结身份见 §0「Gate 3 冻结摘要」，冻结成绩以 `docs/experiments/gate3_holdout_final.json` 为准，本小节不再更新。

## 7.1 Gate 3 目标

回答一个明确问题：

> 在当前冻结语料和新增复杂问题上，有界 Query Decomposition 与 Adaptive Retrieval 是否比单次 BM25 primary 和 Hybrid control 带来可复现收益，收益是否值得额外延迟和成本？

Gate 3 不以“实现了高级 RAG”作为完成标准，而以“完成受控对照并得到可信结论”作为标准。

## 7.2 Baseline

必须同时保留：

1. Primary baseline：Recursive + BM25 + cl100k_content_v1；
2. Control baseline：Recursive + Hybrid + cl100k_content_v1。

原因：

- BM25 是当前冻结基准最佳策略；
- Hybrid 是未来自适应路由与融合分析的重要 control；
- 只与 Hybrid 比较可能掩盖简单 BM25 已经更强的事实；
- 只与 BM25 比较又无法观察融合策略的行为变化。

## 7.3 G3-DESIGN-01：先设计，不写业务实现

产物：

- Gate 3 设计文档；
- ADR；
- QueryPlan Schema 草案；
- 实验矩阵；
- 指标定义；
- sealed holdout 使用纪律；
- 失败分类；
- 停止条件；
- 成本预算。

设计必须明确：

- 什么问题允许分解；
- 什么问题不应分解；
- 最大子问题数；
- 最大检索轮数；
- Router 可选策略；
- 默认 fallback；
- 每次路由如何记录；
- 如何判断证据覆盖；
- 如何计算复杂问题 Gold obligation coverage；
- 如何防止看到 holdout 后调规则。

验收：

- 零业务实现；
- 不修改 Gate 2 Artifact；
- 所有关键字段有 Schema；
- 所有行为有上限；
- 实验矩阵能回答单变量问题。

## 7.4 G3-DATA-02：复杂问题数据与 sealed holdout

新增 30～40 条问题，建议结构：

| 类型 | 最低数量 |
|---|---:|
| 多文档对比 | 8 |
| 多实体或多跳 | 6 |
| 原因分析与证据综合 | 6 |
| 简单事实 control | 5 |
| 无答案、无需检索或不应分解 | 5 |

最低要求：

- 至少 20 条真正需要多个证据义务的问题；
- 每条复杂问题标注 required evidence obligations；
- 对比问题分别标注两侧证据；
- 无答案问题确认语料确实不包含答案；
- 新数据有独立 evaluation_set_id；
- 训练、开发和 holdout 划分写入 Manifest；
- 至少三分之一作为 sealed holdout；
- 实现 Agent 不得读取 holdout 的逐 Case 结果进行调参；
- holdout 只在候选实现、路由规则和阈值冻结后运行。

Gate 2 的 50 条 Case：

- 保持字节不变；
- 作为 regression suite；
- 允许用于 dev failure analysis；
- 不计作新的 sealed holdout。

## 7.5 G3-PLAN-03：QueryPlan Schema

建议模型：

    QueryPlan
      original_query
      query_type
      retrieval_required
      selected_strategy
      reason_code
      subqueries
      max_retrieval_rounds
      fallback_policy
      schema_version

Subquery：

    id
    query
    evidence_obligation
    preferred_strategy
    required

约束：

- 最大 3 个子问题；
- 不输出隐藏思维链；
- reason_code 使用枚举，不要求自由文本推理；
- 原问题必须保留；
- 子问题去重；
- 子问题不可引入原问题没有的新实体；
- Schema 校验失败回退原问题；
- Prompt、模型、temperature 和 Schema version 进入实验身份；
- 原始模型输出与规范化结果都进入 Trace，但敏感内容除外。

问题类型第一版控制在：

- fact；
- comparison；
- causal；
- multi_entity；
- code_symbol；
- troubleshooting；
- unanswerable_or_no_retrieval。

不要一开始设计几十种类型。

## 7.6 G3-DECOMP-04：有界分解

第一版行为：

    简单问题
      → 不分解

    对比、多实体、多证据义务问题
      → 最多 3 个子问题

    Schema 失败、空子问题或重复子问题
      → 回退到原问题单次检索

必须测试：

- 简单问题不被过度分解；
- 对比问题两侧均保留；
- 重复子问题被去除；
- 恶意或异常输出无法突破 Schema；
- 分解失败不会中断主请求；
- 子问题数和字符串长度有上限；
- 同一输入在固定 Fake 下确定；
- 真实 LLM 波动被记录，不伪装成确定性。

## 7.7 G3-MRETR-05：Multi-query Retrieval

职责：

- 对每个子问题独立检索；
- 保留 subquery → chunks → documents 映射；
- Chunk 去重；
- Document 去重；
- 不能让一个高分 Chunk 假装覆盖所有子问题；
- 保留每个通道的分数与 rank；
- 使用稳定 tie-break；
- 支持 fallback 到原问题；
- 输出标准化 EvidenceBundle。

不要把这部分塞进 ExperimentRunner。

建议模块边界：

    core/query_planning/
    core/adaptive_retrieval/
    core/evidence/
    evaluation/gate3/

ExperimentRunner 只编排实验，不承担 Query Planner 和 Router 的业务逻辑。

## 7.8 G3-ADAPT-06：Adaptive Router

第一版优先采用可解释规则或轻量分类器，不必把所有路由交给 LLM。

Router 候选：

- bm25；
- dense；
- hybrid。

每次决策记录：

- selected_strategy；
- reason_code；
- candidate_k；
- final_k；
- reranker_enabled；
- fallback_used；
- latency_ms。

设计原则：

- 当前默认 fallback 应以 BM25 primary 为依据；
- 不因“Hybrid 更高级”默认选择 Hybrid；
- exact term、类名、方法名、错误码可优先 BM25 或 Hybrid；
- 自然语言语义问题是否使用 Dense 或 Hybrid，必须由 dev 结果决定；
- 路由规则和阈值在 holdout 前冻结；
- Router 无收益时允许删除，退回 Decomposition + BM25。

## 7.9 G3-CORRECT-07：有限补检索

不是 Gate 3 第一版必做能力。

只有满足以下条件才实现：

- 已有可测试的 evidence sufficiency signal；
- Dev 上存在明确“第一次检索证据不足、第二次可补齐”的 Case；
- 能与无补检索版本单变量比较；
- 延迟和调用次数预算可接受。

停止策略：

    第一次检索
    → 证据义务未覆盖
    → 最多一次 Query Rewrite 或扩候选
    → 仍不足
    → 返回证据不足或拒答

禁止无限反思或无限改写。

## 7.10 G3-EVAL-08：实验矩阵

最小实验：

| 组 | 策略 |
|---|---|
| A | 单次 BM25 primary |
| B | 单次 Hybrid control |
| C | Decomposition + BM25 |
| D | Decomposition + Adaptive Retrieval |
| E | D + 一次 Corrective Retrieval，仅在 G3-CORRECT-07 通过时 |

指标：

### 检索结果

- Hit@K；
- Recall@K；
- MRR；
- nDCG@K；
- Gold obligation coverage；
- 子问题覆盖率；
- 多文档完整召回率；
- 空结果率。

### 规划质量

- Schema validity；
- 不必要分解率；
- 无效分解率；
- 子问题重复率；
- 新实体引入率；
- fallback rate。

### 系统代价

- 平均检索调用数；
- P50/P95 latency；
- Planner Token；
- 总 Token；
- 估算成本；
- 超时率；
- 错误率。

### 分层报告

- simple；
- comparison；
- multi_entity；
- causal；
- code_symbol；
- unanswerable；
- dev；
- sealed holdout。

不得只报告总体平均分。

## 7.11 Gate 3 退出条件

- 新 evaluation_set 和 holdout 已冻结；
- QueryPlan 结构化并有版本；
- 最大子问题、最大轮数和 fallback 明确；
- Multi-query 保留证据映射；
- Router 可解释；
- 与 BM25 primary 和 Hybrid control 都有正式对照；
- 先在 dev 定规则，再在 sealed holdout 验证；
- 至少一类复杂问题有稳定收益；
- 简单问题没有明显退化；
- 报告额外延迟、调用和成本；
- 无收益能力被删除或降级；
- 有逐 Case 失败分析；
- 结论和 Artifact 冻结；
- 未实现内容不写进 README 和简历。

---

# 8. GraphRAG 决策 Gate

GraphRAG 不自动进入 Gate 3 或 Gate 4。

只有同时满足以下条件才立项：

- 语料存在稳定、可抽取的代码或配置关系；
- 至少 15～20 条关系型、多跳问题；
- BM25、Hybrid、Decomposition 和 Adaptive Retrieval 在该子集上明显不足；
- 关系优先来自 AST、静态分析或确定性规则；
- GraphRetriever 可以作为独立 Tool 或 Retriever 与 Baseline 对照；
- 有明确增益、延迟和失败分析；
- 用户拍板同意插入。

可考虑的关系：

- Class DEFINES Method；
- Method CALLS Method；
- Controller CALLS Service；
- Service CALLS Repository；
- Repository ACCESSES Table；
- ConfigKey AFFECTS Component；
- Module DEPENDS_ON Module。

不建议：

- 用 LLM 对全部文本自由抽图；
- 让图替代 Dense、BM25 和 Hybrid；
- 因为“GraphRAG 最新”就改变主线；
- 没有关系型评测集就声称提升。

---

# 9. Gate 4：结构化 Tool Agent

## 9.1 Agent 定义

Agent 必须满足：

> 根据任务选择受允许的 Tool，生成结构化参数，执行并观察结果，在步数、时间、Token 和权限预算内完成任务，并输出可复现 Trace。

第一版只做单 Agent。

## 9.2 DATA-CONSIST-01 与 Gate 4 的关系

**DATA-CONSIST-01 = P1 engineering debt**（与 §5.3 一致）。

它**不阻塞** Gate 4 v1 的 read-only Tool 主线：

- knowledge_search；
- code_search；
- calculator；
- structured Tool Selection；
- bounded read-only Tool Runtime。

但以下任一条件发生前，必须重新审查并完成相应一致性收口：

1. 引入任何 state-mutating Tool；
2. Tool 可以修改知识库、文件、Git、数据库等持久状态；
3. 进入 public release / 对公网部署阶段。

原删除一致性、document identity、API citation 等收口项属于 **DATA-CONSIST-01 future scope**，不是 Gate 4 read-only v1 的 blocking prerequisite：

- 删除操作不吞异常；
- Dense 与 Sparse 删除具有一致性策略；
- 文档身份不再只依赖 basename；
- 同名文件行为有明确契约；
- API 保留 citation_id；
- API 返回 citation validation 或等价结构；
- Retrieval output 有稳定 Schema。

原因：

> Tool Agent 会放大底层数据契约问题。底层状态可能分叉时，Agent Trace 再漂亮也不可信；但 read-only v1 的只读工具不触碰写路径，因此 DATA-CONSIST-01 不作为 Gate 4 read-only v1 的前置阻塞。

## 9.3 第一批 Tool（v4 冻结范围：3 个 read-only 工具）

设计契约以 `docs/design/g4_structured_tool_agent.md` 为准。Gate 4 v1 冻结 **3 个 read-only 工具**：

### knowledge_search

- 在项目技术知识库中检索证据，复用现有 RAG / Retrieval 能力（通过 Tool Adapter）；
- `query` 由模型控制；`top_k` / retriever internal config / index identity 默认由系统配置控制，模型不得任意扩大；
- **不重跑 Gate 3 frozen RAG**。

### code_search

- 只读搜索当前项目中的代码 / 技术文件；
- v1 必须限定：repo-root 内、read-only、无文件修改、无 shell、无路径逃逸。

### calculator

- 确定性算术 / 数值计算；
- **不得 `eval(user_input)`**；未来实现使用受控 parser / allowlisted arithmetic evaluator。

v1 明确不做：shell / terminal / 任意 Python execution / 文件写入 / Git write / 任意 HTTP fetch / 浏览器自动操作 / 数据库写 / 邮件 / MCP 动态工具发现 / 插件 marketplace / multi-agent（以后确实需要时单独立项）。

（v3 草案中的 `get_document_context` / `inspect_retrieval_experiment` 不进入 v1 冻结范围，可作后续候选，不自动立项。）

## 9.4 Agent Runtime（与设计契约对齐，见 `docs/design/g4_structured_tool_agent.md`）

### 内部执行绑定：RegisteredTool / ToolHandler / ToolAdapter

```
RegisteredTool
├── spec: ToolSpec        ← 模型唯一可见面（input_schema / output_schema）
└── handler: ToolHandler  ← 系统注册的执行实现，不序列化给模型
```

语义锁死：

- 模型只能看到 `ToolSpec`，只能输出 `tool_name` + `arguments`；
- `handler` 只由系统注册；handler 不序列化给模型；handler 不允许来自 ToolCall；
- Executor 只能通过 Registry resolve 到 handler，禁止模型指定 callable / 函数路径 / 任意代码执行。

### Executor 执行流程（固定顺序）

```
resolve RegisteredTool（查 Registry，未注册 → UNKNOWN_TOOL）
→ validate input_schema
→ permission / allowlist
→ budget（硬预算检查）
→ handler.execute(...)
→ validate output_schema
→ safe normalize / truncate
→ ToolObservation
```

### 第一阶段硬预算（v1）

| 预算 | 默认值 |
|---|---:|
| max_agent_iterations | 5 |
| max_tool_calls | 4 |
| max_tool_errors | 2 |

- 系统预算，LLM 无权提高；预算用尽进入固定收尾（final_answer 或 refuse）；
- 时间 / Token 预算、Tool timeout、用户取消、无进展检测**不删除长期方向**，但标为 **later hardening / Gate 4 close candidate**，不作为 G4-TOOL-02 的 v1 实现要求。

最小 AgentState（v1；时间 / Token 字段列为 later hardening）：

    task_id
    user_query
    step
    tool_calls
    observations
    evidence
    status
    final_answer
    warnings

执行循环（v1，bounded）：

    用户任务
    → 模型 Decision → AgentAction
    → tool_call：resolve → validate input_schema → permission → budget → handler.execute → validate output_schema → safe normalize → ToolObservation
    → 模型读取 Observation 后再次决策（受 max_agent_iterations / max_tool_calls / max_tool_errors 约束）
    → final_answer / refuse 收尾
    → Trace 落盘

禁止解析字符串式 ReAct。

> 以上全部为设计契约，不冒充任何已实现代码（G4-TOOL-02 尚未开始）。

## 9.5 停止与安全

### v1 必须

- max_agent_iterations / max_tool_calls / max_tool_errors（硬预算）；
- 相同 tool_name + arguments 连续失败阻止（计入 max_tool_errors）；
- 完全相同的 ToolCall 去重；
- Tool allowlist；
- 文档内容与系统指令隔离；
- Prompt Injection 测试；
- 敏感 Tool 默认禁止。

### later hardening（Gate 4 close candidate，v1 不要求）

- 最大总耗时（time budget）；
- Token 预算；
- Tool timeout；
- 重试上限（v1 无自动重试，此为后续策略）；
- 用户取消；
- 无进展检测。

### 不展示（面向模型 / Trace / UI）

- 隐藏思维链；
- 原始系统 Prompt；
- API Key；
- 敏感路径；
- 未过滤的内部异常。

### 展示

- 计划摘要；
- Tool 名称；
- 规范化参数；
- Tool 结果摘要（安全截断）；
- 证据和引用；
- 进度；
- 最终状态。

## 9.6 Agent Evaluation

任务集至少包括：

- 单 Tool；
- 多 Tool；
- 需要补检索；
- Tool 参数错误；
- Tool timeout；
- 无答案；
- 代码与文档联合；
- 查询实验结果；
- 重复调用诱导；
- Prompt Injection。

指标：

- Tool 选择准确率；
- Tool 参数有效率；
- 任务完成率；
- 最终答案正确率；
- Citation support；
- 平均步骤；
- 无效调用率；
- 重复调用率；
- 终止正确率；
- 超预算率；
- 延迟；
- Token；
- 成本；
- 失败分类。

## 9.7 Gate 4 退出条件

- 原生 Tool Calling；
- Tool 输入输出都有 Schema；
- 至少三个实际 Tool；
- 单 Agent 完成至少三类任务；
- 有步骤、时间、Token 和重复调用限制；
- Trace 可复现；
- Tool 错误可见；
- 有 Agent 专项数据与正式结果；
- Prompt Injection 边界有测试；
- UI 只展示结构化轨迹；
- 不依赖多 Agent 完成核心 Demo。

## 9.8 Gate 4 冻结阶段路线（写死，不允许跳步）

设计契约：`docs/design/g4_structured_tool_agent.md`。

```
G4-DESIGN-01   Structured Tool Agent contract            ← 本任务 = IN PROGRESS
        ↓
G4-TOOL-02     ToolSpec + ToolRegistry + ToolExecutor
        ↓
G4-TOOLS-03    knowledge_search + code_search + calculator
        ↓
G4-AGENT-04    真实 LLM structured Tool Selection
        ↓
G4-RUNTIME-05  Bounded Decision → Tool → Observation loop
        ↓
G4-EVAL-06     Tool Agent Dev benchmark + error/recovery evaluation
        ↓
G4-E2E-07      API / trace / real multi-tool task
        ↓
G4-CLOSE-08    Freeze / final review
```

目前：

- 只有 `G4-DESIGN-01` = **IN PROGRESS**；
- 其余全部 **NOT STARTED**；
- **不能提前声称已实现**（README 与简历只写"Gate 4 设计契约已冻结"，不写"已实现 Tool Agent"）。

关键契约（详见设计文档，语义不可破坏）：

- Gate 3 frozen runtime 不被 Gate 4 反向改写；能力经 Tool Adapter 复用；未来独立 namespace `core/tool_agent/`；新入口 `/tool-agent/query`，不改冻结 `/agent/query`；
- ToolSpec（name 唯一 / Registry 是真相来源 / 模型不能动态建工具 / 不能指定 Python module/class/function / input 强 schema / unknown argument 拒绝）；
- ToolCall 的 call_id 由 Runtime 生成，不由 LLM 生成；
- ToolObservation 是事实结果、不是 CoT，不含 traceback / secret / Key；
- AgentAction = 强判别联合（tool_call / final_answer / refuse），不做 `{thought, tool}` 半结构化；
- ToolRegistry 与 ToolExecutor 分层，Executor 不接受任意 import / 函数路径 / shell / eval；
- RegisteredTool 绑定（spec + handler）：模型只见 ToolSpec、只输出 tool_name + arguments；handler 系统注册、不序列化、不来自 ToolCall；Executor 只经 Registry resolve handler；
- Bounded loop：默认 `max_agent_iterations=5` / `max_tool_calls=4` / `max_tool_errors=2`，系统预算，LLM 不能提高；v1 无自动工具重试；
- Tool error ≠ Agent process crash（8 类错误码，结构化 Observation 供 Agent 恢复）；
- Trace ≠ CoT，Observation/Trace 有大小与安全边界（禁 Key / Authorization / env secret / raw system prompt / private CoT / traceback / 无限制全文 / 本地敏感绝对路径）。

## 9.9 Gate 4 评测口径（本阶段只预注册，不创建 benchmark）

预注册指标：

- tool_selection_accuracy
- argument_schema_validity
- task_success_rate
- unnecessary_tool_call_rate
- tool_error_recovery_rate
- budget_violation_count
- loop_termination_rate
- final_answer_grounding / evidence usage

任务类型（未来至少）：

- no_tool
- single_tool
- multi_tool
- tool_error
- unanswerable / refusal

口径：

> 最终不能只拿"Tool Call JSON 合法率"冒充 Agent 成功率。JSON 合法只说明格式对，不说明工具选对、任务完成、答案有证据。

---

# 10. Gate 5：端到端评测与工程收口

Gate 5 不等于“堆基础设施”。目标是让招聘方和新环境都能验证项目。

## 10.1 G5-E2E-01：生成、引用和拒答评测

必须补齐：

- Answer correctness；
- Answer relevance；
- Faithfulness；
- Citation format validity；
- Citation coverage；
- Citation support；
- Unsupported claim rate；
- 拒答准确率；
- 有答案问题误拒答率；
- Prompt Injection；
- 输入、输出和总 Token；
- 成本；
- 端到端 P50/P95 latency。

LLM-as-a-Judge 必须：

- 固定 Prompt 和模型；
- 进入实验身份；
- 保存逐样本理由摘要和原始分数；
- 抽样人工校准；
- 不把 Judge 当绝对真值。

Reranker 正式消融也在此补齐：

- Retriever；
- Retriever + Reranker；
- 排序收益；
- 延迟；
- candidate_k；
- final_k；
- 代码和中文问题分层。

## 10.2 G5-ENV-02：依赖与复现

- pyproject.toml；
- uv.lock 或等价 lockfile；
- 固定 Python 版本；
- .env.example；
- 模型名称与 revision；
- CPU/GPU 降级说明；
- 可公开最小语料和评测样例；
- 单命令重建一组小实验；
- 不提交密钥、模型缓存和私人语料。

## 10.3 G5-CI-03：CI

GitHub Actions 至少运行：

- 单元测试；
- 不依赖真实大模型下载的集成测试；
- 格式检查；
- 适量静态检查；
- Artifact Schema 校验；
- freeze JSON 一致性或不可变性检查。

大型 BGE、Reranker 和外部 LLM 测试使用 marker、Fake 或人工触发。

## 10.4 G5-DOCKER-04：最小一键启动

- API Dockerfile；
- UI 可选；
- Docker Compose；
- 健康检查；
- 数据和模型缓存挂载；
- 默认仅本地绑定；
- 明确配置和资源要求。

不需要 Kubernetes。

## 10.5 G5-TRACE-05：结构化可观测性

至少记录：

- trace_id；
- request_id；
- route；
- subqueries；
- Dense、Sparse 候选；
- RRF；
- Rerank；
- Context budget；
- Tool Calls；
- Token usage；
- latency；
- warnings；
- error stage。

日志不记录密钥和不必要的敏感原文。

## 10.6 G5-SSE-06：结构化事件

事件至少包括：

- request_started；
- planning_completed；
- retrieval_started；
- retrieval_completed；
- tool_started；
- tool_completed；
- generation_delta；
- generation_completed；
- request_failed。

事件有稳定 Schema，不只返回拼接字符串。

## 10.7 G5-PERF-07：最小性能报告

记录：

- 索引耗时；
- 冷启动与热启动；
- 单查询 P50/P95；
- 并发 1、5、10；
- Embedding、Retrieval、Rerank、LLM 分阶段；
- 内存和设备；
- 错误率；
- 超时率；
- Token 和成本。

目标是能解释，不是伪装互联网规模。

## 10.8 G5-README-08：公开展示

README 必须包含：

- 项目解决的问题；
- 当前真实能力；
- 架构；
- 快速启动；
- 实验框架；
- 冻结 Baseline；
- 关键实验表；
- 失败案例；
- Demo；
- 已知限制；
- Roadmap；
- 未实现项；
- 复现命令。

README 必须明确：

- Gate 2 是 retrieval-level freeze；
- Gate 3 和 Agent 的实际状态；
- 数字适用范围；
- 语料和数据能否公开；
- API 默认安全边界。

## 10.9 Java 差异化

只在 Python RAG 和 Agent 主线完成后考虑最小 Spring Boot 服务。

可负责：

- 用户与会话；
- 知识库元数据；
- Agent 任务状态；
- 鉴权；
- 限流；
- SSE 代理；
- 必要时 MySQL 或 Redis。

Python 保留：

- 文档解析；
- Embedding；
- Retrieval；
- Rerank；
- Agent Runtime；
- Evaluation。

不为了“有 Java”重写全部 AI 链路。

## 10.10 Gate 5 退出条件

- 新环境按 README 启动；
- CI 通过；
- lockfile；
- Docker 可运行；
- 上传边界安全；
- 数据删除一致；
- 引用契约不在 API 层丢失；
- 端到端评测；
- Trace；
- 结构化 SSE；
- 最小性能报告；
- 五分钟 Demo；
- 简历数字可追溯；
- 已知限制诚实。

---

# 11. 学习路线

学习与当前任务绑定，不单独追热门名词。

## 11.1 Gate 1 与 Gate 2 复盘

必须能闭卷解释：

- 为什么 Reranker 不能只接最终 5 条；
- BM25 为什么需要独立候选池；
- RRF 缺席通道为什么贡献 0；
- 为什么 tie-break 影响复现；
- 为什么 Chunker 改动必须重建索引；
- 为什么 corpus_id、evaluation_set_id、experiment_id 和 run_id 都需要；
- 为什么只保存平均 Recall 不够；
- 为什么声明配置还要做 runtime binding；
- Tokenizer Level 1、2、3 分别是什么；
- 为什么有控制变量仍不能随意解释细粒度机制。

## 11.2 Gate 3 学习

- Query Classification；
- Query Rewrite；
- Multi-query；
- Query Decomposition；
- Adaptive Retrieval；
- Corrective RAG；
- Evidence Obligation；
- Router；
- Stop Policy；
- 数据泄漏；
- Dev 与 sealed holdout；
- 分层评测。

必须能解释：

- 分解为什么可能比不分解更差；
- 什么问题不应分解；
- 为什么当前 BM25 是 primary；
- Router 如何证明有效；
- 如何限制额外调用；
- 为什么不能用已经看过很多次的 50 条 Case 证明泛化。

## 11.3 Gate 4 学习

- 原生 Tool Calling；
- JSON Schema；
- Tool Registry；
- Agent State；
- Observation；
- Idempotency；
- Retry 与 Timeout；
- Budget；
- Prompt Injection；
- Permission Boundary；
- Trace；
- Agent Evaluation。

必须能解释：

- Agent 与固定 Workflow 的区别；
- 为什么不解析字符串 ReAct；
- 如何防止死循环；
- 如何处理 Tool 失败；
- 如何判断 Tool 选择正确；
- 为什么不展示隐藏 Thought。

## 11.4 Gate 5 学习

- FastAPI 上传安全；
- CORS；
- 统一错误码；
- 依赖锁定；
- GitHub Actions；
- Docker；
- SSE；
- 结构化日志与 Trace；
- 性能测试；
- Java 与 Python 服务边界；
- 数据一致性与补偿。

---

# 12. 防止路线漂移

遇到新技术先回答：

1. 它解决当前哪类失败？
2. 是否有 Baseline？
3. 是否可单变量比较？
4. 是否有数据集？
5. 是否有退出条件？
6. 延迟和成本是多少？
7. 无收益时是否愿意删除？
8. 是否重复已有 Pipeline、Router 或 Tool？
9. 是否会越过当前 Gate？

回答不清，进入 Backlog。

允许临时插入：

- 数据损坏；
- 虚假实验；
- 严重安全；
- 当前任务无法继续的环境阻塞；
- 最新提交导致回归。

不允许临时插入：

- 新框架发布；
- 热门 Agent Demo；
- “别人都在做”；
- UI 美化；
- 大目录重构；
- 增加数据库种类；
- 过早微服务化。

---

# 13. 标准任务卡

每张任务卡使用：

    所属 Gate：
    任务编号：
    任务类型：

    背景：

    本次唯一目标：

    要求：
    1.
    2.

    必须增加的测试：
    1.
    2.

    明确不做：
    -

    验收命令：
    - 目标测试：
    - 相关测试：
    - 全量测试：

    汇报：
    - 修改文件
    - 实现说明
    - 测试命令
    - 测试结果
    - 未处理问题

    完成后提交并等待复审。

审计方必须独立检查：

- diff 是否越界；
- 测试是否覆盖真实结果；
- Mock 是否掩盖 Bug；
- 异常是否被吞；
- 公共契约是否变化；
- Artifact 是否被偷偷改写；
- 文档是否夸大；
- 命令是否真实运行；
- 结果是否来自最新 HEAD。

---

# 14. 文档治理

建议最终目录：

    README.md
    docs/
      roadmap.md
      status.md
      HANDOFF.md
      architecture.md
      evaluation.md
      agent-design.md
      known-issues.md
      decisions/
      experiments/
      study-notes/
      archive/

短期文档任务：

### DOC-HOUSEKEEP-01

- 将 HANDOFF 中“Gate 2 全部任务完成，待 closure 复审”改为 CLOSED / FROZEN；
- 补 G2-CLOSE-22-R4；
- 保持 freeze JSON 字节不变；
- 不重新打开 Gate 2；
- 不新增业务代码；
- 新增 study-notes 索引，至少标记 current、superseded、history；
- 路线图 v2 归档，v3 成为长期主路线。

README 重写不塞入这个小任务，放到 G5-README-08；但 SEC-P0-01 应同步修改危险的公开启动说明。

---

# 15. 校招投递节点

## 15.1 当前即可使用的项目叙事

当前可以诚实写：

> 实现面向技术文档与代码的可评测 RAG 系统，支持 Dense、BM25、RRF Hybrid 与 Cross-Encoder 重排序；构建隔离实验框架，对语料、评测集、配置、运行时 Retriever 和 Tokenizer 契约进行稳定身份绑定，保存逐样本候选、分数、排名和指标，并完成 9 组正式检索消融与失败分析。

可写真实结果：

> 在当前 37 份技术资料、50 条人工审核问题的 Top-5 文档级检索基准上，Recursive + BM25 取得 Hit@5 0.98、Recall@5 0.9533、nDCG@5 0.8206。

必须附范围，不能写成通用效果。

## 15.2 当前不能写

- 已实现 Query Decomposition；
- 已实现 Adaptive Retrieval；
- 已实现 Agentic RAG；
- 已实现 Tool Agent；
- GraphRAG 提升了效果；
- 生成答案 Faithfulness 已完成系统评测；
- 项目已生产可用；
- 支持高并发或分布式部署。

## 15.3 Gate 3 后升级

只有 Gate 3 frozen 后才写：

> 在冻结 Baseline 上实现有界 Query Decomposition 与 Adaptive Retrieval，并通过独立复杂问题集和 sealed holdout 对比复杂问题覆盖率、延迟与成本。

数字必须来自 Gate 3 Artifact。

## 15.4 Gate 4 后升级

只有 Gate 4 frozen 后才写：

> 将 RAG 能力封装为结构化 Tool，基于原生 Tool Calling 实现单 Agent Runtime，通过 Schema、权限、步数、时间、Token 预算和 Trace 控制执行，并评测 Tool 选择、任务完成率和失败终止。

---

# 16. 五分钟 Demo 目标

最终 Demo：

1. 索引技术文档和 Java 代码；
2. 简单问题展示 BM25 primary；
3. 复杂问题展示 QueryPlan 和子问题证据；
4. 展示 Adaptive Router 决策摘要；
5. 展示 Tool Agent 调用知识检索与代码搜索；
6. 输出带稳定 Citation 的答案；
7. 展示 Gate 2 与 Gate 3 实验表；
8. 展示失败、拒答或 Tool timeout；
9. 展示结构化 Trace；
10. 明确已知限制。

不展示隐藏思维链。

---

# 17. Backlog

## P1

- 正式文档身份与版本模型；
- Citation Support 自动评判；
- Prompt Injection 扩展集；
- 代码符号解析；
- Trace UI；
- Java 最小服务。

## P2

- SQLite 元数据；
- 旧索引清理；
- OpenTelemetry；
- Prometheus；
- 权限过滤；
- GraphRetriever；
- AST 依赖图；
- 缓存；
- 并发控制。

## P3

- 多 Agent；
- Kubernetes；
- Kafka；
- 多向量库；
- 大规模蓝绿索引；
- 完整 IAM；
- 模型微调；
- 自动 Prompt 进化。

Backlog 不代表必须完成。

---

# 18. 最终 Definition of Done

## 功能

- 文档与代码入库；
- Dense、BM25、Hybrid、Rerank；
- 引用与拒答；
- Query Decomposition；
- Adaptive Retrieval；
- 至少三个结构化 Tool；
- 单 Agent；
- 结构化 Trace。

## 评测

- Gate 2 冻结检索基准；
- Gate 3 新复杂问题集；
- sealed holdout；
- 逐样本结果；
- Advanced RAG 对照；
- 生成与 Citation 评测；
- Agent 评测；
- 失败分析；
- 延迟、Token 和成本。

## 工程

- 自动测试；
- CI；
- lockfile；
- Docker；
- 安全上传；
- 稳定文档身份；
- Dense 与 Sparse 一致性；
- 统一错误码；
- SSE；
- Trace；
- 基础性能报告。

## 展示

- README；
- 架构图；
- 实验报告；
- 五分钟 Demo；
- 已知限制；
- 简历项目描述；
- 面试复盘。

## 诚实性

- 未验收功能不写入简历；
- 不用 Mock 数字；
- 不把 UI 历史显示称为真正多轮；
- 不把固定 Workflow 称为 Agent；
- 不因使用 GraphRAG 就声称提升；
- 不展示隐藏 Thought；
- 所有数字可追溯到 Artifact；
- 所有结论标明范围和证据级别。

---

# 19. 当前接管指令

每次开始：

1. 查看远端最新 HEAD；
2. 读取 docs/status.md；
3. 若涉及 Gate 2 数字，读取 gate2_freeze.json；
4. 查看当前唯一任务卡；
5. 检查相关源码和测试；
6. 不从 Backlog 随机选任务；
7. 完成后跑目标、相关和全量测试；
8. 提交后由审计方独立复审；
9. 用户拍板后才进入下一项。

当前下一任务：

> G4-DESIGN-01：冻结 Gate 4 Structured Tool Agent 的架构边界、核心数据契约、执行模型、安全边界、阶段路线与评测口径（docs/design/g4_structured_tool_agent.md）；纯设计，不写 Tool、不调用 LLM、不运行实验。

其后（写死顺序，不允许跳步）：

> G4-TOOL-02（ToolSpec + ToolRegistry + ToolExecutor）→ G4-TOOLS-03（knowledge_search + code_search + calculator）→ G4-AGENT-04（真实 LLM structured Tool Selection）→ G4-RUNTIME-05（Bounded Decision → Tool → Observation loop）→ G4-EVAL-06（Tool Agent Dev benchmark + error/recovery evaluation）→ G4-E2E-07（API / trace / real multi-tool task）→ G4-CLOSE-08（Freeze / final review）。

Gate 3 已 CLOSED / FROZEN：不重新打开，不重跑其冻结 RAG。

---

# 20. 最后原则

项目接下来的分水岭是：

    一份不会泄漏的 Gate 3 评测协议
    → 一组 Query Decomposition 的真实增益或负结果
    → 一个受控、可评测的 Tool Agent
    → 一套新环境可复现、公开边界安全的工程交付

如果 Gate 3 证明 Query Decomposition 没有稳定收益，这也是有效结果。

项目最有价值的不是“用了最新 RAG 名词”，而是：

- 能发现真实 Bug；
- 能建立冻结 Baseline；
- 能用数据否定直觉；
- 能把未验证因果说清楚；
- 能让 Agent 在权限和预算内执行；
- 能让每个简历数字回到代码、测试和 Artifact。

继续遵守一次一项、Gate 验收和用户拍板，项目就不会因为换 Agent、额度不足或新技术热点而失去方向。
