# 可评测 RAG Agent 项目主路线图 v6

> 项目：`wgqa/my_agent`  
> 路线图版本：**v6（Evidence-Grounded AI Engineering Agent）**  
> 编写日期：**2026-08-22**  
> 当前远端基线：`2603ab788b6dbb4b079f5383525fb9d2cea8d388`（`fix: normalize generator failure semantics`）  
> Release 1.0 冻结提交：`75ae103f3a3483ef3213fbd5520c8b06bb0157ce`  
> 数据仓库：`wgqa/agent_data`  
> 冻结领域知识 corpus：`agent_ai_v1/02_corpus_candidate`，37 documents，corpus_id=`870e5864df67`

---

# 0. v6 的核心决策

v6 不再继续扩大“泛 Software Engineering Agent”概念，也不把项目改造成 EvoAgent 的简化复刻。

**正式项目定位冻结为：**

# Evidence-Grounded AI Engineering Agent

中文：

> **面向 AI / RAG / Agent 研发场景的可评测智能研发 Agent**

系统面向 RAG、LLM Application、Agent、MCP、Tool Calling、Vector DB、Prompt、Deployment 等 AI 应用研发场景，在**长期共享的领域知识**与**当前真实代码仓库**之间进行异构证据检索、工具调用、诊断与验证。

一句话项目描述：

> 融合可评测 Knowledge RAG、按需代码仓库检索、Structured Tool Use、Conversation Context 与 Evidence Verification，支持技术知识问答、项目理解、理论到实现映射、配置分析、故障诊断、变更影响与测试建议。

v6 的总原则：

> **先把 Core AI Engineering Agent 做成完整系统，再选择性吸收 EvoAgent 等前沿 Agent System 的 Runtime、Specialist/Critic、Checkpoint、Multi-Agent 与 Controlled Evolution 思想。高级能力用于增强技术广度，但不能反过来改变项目主线。**

---

# 1. 为什么从 v5 调整到 v6

## 1.1 v5 的问题不是技术错误，而是产品边界过宽

v5 把 Release 2.0 推向“真实软件研发场景中的 Engineering Agent”，这个方向帮助项目走出了纯技术问答 Demo，但继续泛化会产生两个问题：

1. 当前冻结 Knowledge RAG 的 37 份资料高度集中在 AI/RAG/Agent/LLM 工程，而不是 Spring、JVM、MySQL、Redis、Kafka 等泛后端知识；
2. 如果强行称为“万能 Software Engineering Agent”，Knowledge RAG 与真实代码仓库之间的业务语义会逐渐脱节。

因此 v6 不否定 v5 的工程 Agent 路线，而是**把垂直领域重新对齐到已有数据资产和技术积累**。

## 1.2 v6 不等于“RAG + EvoAgent”

项目真实演进顺序是：

`Basic RAG`
→ `可评测 Retrieval`
→ `Agentic RAG`
→ `Structured Tool Agent`
→ `Repository Evidence`
→ `Context Engineering`
→ `Reliability`
→ `AI Engineering Agent`

因此项目应被描述为：

> **RAG-first / Evidence-first 的 Agent System，后续吸收 EvoAgent 类系统的高级 Runtime 与演进机制。**

而不是：

> “删减版 EvoAgent + 外挂 RAG”。

---

# 2. 目标用户与核心任务

## 2.1 目标用户

主要 Persona：

- RAG / Agent 项目开发者；
- AI Application Engineer；
- Java / Backend 开发者转向 RAG / Agent 工程；
- 维护已有 RAG / Agent 项目的研发人员；
- 需要理解陌生 AI 工程仓库的面试者 / 新成员。

## 2.2 Core 用户任务

Release 2.0 Core 必须真正覆盖以下任务，而不是只扩大架构图。

### A. 技术知识问答
- Hybrid Retrieval 为什么可能优于 Dense-only？
- RRF 的核心机制是什么？
- MCP 的 capability discovery 和 transport 有什么区别？

### B. 项目 / 代码理解
- 这个项目的 HybridRetriever 在哪里实现？
- Planner → Retrieval → Verifier 的调用链是什么？
- 某配置项在哪里读取并生效？

### C. 理论与实现对照
- 项目里的 RRF 实现与标准 RRF 有什么差异？
- 当前 Context Resolver 的实现是否符合 bounded recent context 设计？

### D. 工程诊断
- 为什么修改检索逻辑后 Recall 下降？
- 为什么 Agent 会重复调用工具？
- 为什么某个问题最终被 Verifier 拒答？

### E. Change Impact / Test Recommendation
- 这次 diff 修改了哪些模块？
- 可能影响哪些路径？
- 应重点运行哪些测试？

### F. Docs-Code Consistency
- README 描述的流程和当前实现一致吗？
- 文档里的配置名是否仍存在于代码？

---

# 3. 四层核心架构

```text
┌─────────────────────────────────────────────────────┐
│              AI Engineering Tasks                   │
│ QA / Repo Understanding / Diagnosis / Impact        │
│ Docs-Code Consistency / Test Recommendation         │
├─────────────────────────────────────────────────────┤
│                 Agent Runtime                       │
│ Planner / Router / Context / Tool Loop / Verifier   │
│ Budget / Safe Trace / Structured Failure            │
├───────────────────────┬─────────────────────────────┤
│ Knowledge Evidence    │ Repository / Change Evidence│
│ Persistent RAG        │ On-demand Retrieval         │
│ BM25 / Dense / Hybrid │ code_search                 │
│ Reranker / Citation   │ read_project_context        │
│                       │ git_diff / changed_files    │
│                       │ refs / config / tests       │
├───────────────────────┴─────────────────────────────┤
│             Evaluation & Diagnostics                │
│ Retrieval / Agent / Tool / Context / Engineering    │
│ Failure Analysis / A-B / Cost / Latency             │
└─────────────────────────────────────────────────────┘
```

核心设计思想：

> **Agent 是上层决策与编排；RAG、代码检索、Git、测试定位等是异构 Evidence Backend。**

---

# 4. RAG 与代码仓库的正式边界

## 4.1 Knowledge RAG：长期共享、提前索引

适用于稳定、长期复用的 AI/RAG/Agent 领域知识。当前冻结 corpus：

- repository：`wgqa/agent_data`
- commit：`179f18e812ad63c36c5569de8e86c5ff9a931cb5`
- path：`agent_ai_v1/02_corpus_candidate`
- documents：37
- corpus_id：`870e5864df67`

## 4.2 Repository Retrieval：默认按需，不建立每仓库 Vector DB

对临时代码仓库默认使用：

- exact / lexical search；
- symbol / path search；
- `code_search`；
- `read_project_context`；
- Git diff / changed files；
- test / config / reference search。

**禁止默认流程：**

`clone repo → 全量 chunk → 全量 embedding → 建 vector DB → 才能开始回答`

## 4.3 Repository Semantic Index：条件能力

只有满足以下条件之一才考虑：

1. 大型 repo 的自然语言语义定位被证明是当前工具的主要瓶颈；
2. 同一 repo 会长期重复分析；
3. A/B 证明 semantic code retrieval 显著优于 lexical/symbol baseline。

若未来实现：

- 与 Knowledge RAG Vector Store 隔离；
- 绑定 `repo_id + commit_sha`；
- 可缓存；
- 优先增量更新；
- 不污染历史冻结 Benchmark。

---

# 5. 当前项目真实状态（v6 起点）

## Release 1.0
**CLOSED / FROZEN**

已完成 Basic RAG、Retrieval Evaluation、Agentic RAG、Structured Tool Agent、Safe Trace、API/UI/CI/Smoke 与 Release Freeze。

## Release 2.0 已完成能力

### G6 — Repository / Engineering Evidence
已完成 workspace binding、`code_search`、`read_project_context`、Engineering Evidence 与两个真实 Spring repo 实验。

结论：

> 按需代码导航是当前默认 repo evidence strategy；Project RAG 暂无证据支持。

### G7 — Observable Demo / UI
已完成 Chat-first UI、Answer / Sources / Engineering Evidence、Planner / Route / Verification / Safe Trace。

Execution Ledger：**DEFERRED / OPTIONAL**

### G8 — Conversation Context
已完成：

- recent context max 6 messages；
- 1200-token bounded context；
- standalone query resolver；
- expected provider failure safe fallback；
- programming bug fail-fast；
- clean-corpus A/B。

正式 R1：

- no-history PASS = 3/6；
- with-history PASS = 5/6；
- improved / equal / regressed = 2 / 4 / 0；
- topic switch 无退化。

结论：

**MIXED / USEFUL BUT NOT GENERAL**

暂不继续堆 Long-term Memory / Vector Memory。

### G9-RELIABILITY-01 — Generator Failure Semantics
当前基线：

`2603ab788b6dbb4b079f5383525fb9d2cea8d388`

已完成：

- typed Generator errors；
- timeout / auth / unavailable / invalid-response 分类；
- DeepSeek 保留有限 retry；
- error placeholder 不再伪装成正常 answer；
- Basic `/query` 生成失败返回通用 HTTP 500；
- Agentic generation failure → `GENERATION_FAILED`；
- unknown programming bug 不伪装为 provider failure；
- safe failure 不泄漏 provider text / key / local path；
- Study Note 105。

**G9-RELIABILITY-01 = CLOSED**

---

# 6. v6 主路线：先完成 Core Agent System

从这里开始，路线不再以“加更多 Agent 概念”为目标，而以**扩大真实 AI Engineering Task 面**为目标。

## Phase A — Core Evidence Tools Expansion

### A1. Git / Change Evidence

最小候选：

- `changed_files`
- `git_diff`

要求：

- read-only；
- workspace-bound；
- bounded output；
- 不泄漏绝对路径；
- 不执行任意 Git command；
- binary / huge diff 有明确截断。

DoD：

- 能回答“这次修改了哪些文件？”
- 能回答“这个 diff 改了什么逻辑？”
- 能为 Change Impact 提供可追溯 evidence。

### A2. Test Evidence

目标：支持“改动后该跑什么测试”。

第一版使用简单、可解释策略：

- changed file / symbol；
- 同模块 tests；
- 直接引用；
- 输出候选测试与证据。

不先做复杂 dependency graph。

### A3. Config / Reference Evidence

只有真实任务需要时增加。

优先复用或扩展已有 `code_search`，不要为了工具数量拆多个重复 Tool。

---

# 7. Phase B — Core AI Engineering Workflows

## B1. Implementation Understanding
“项目里的 Adaptive Retrieval 是怎么工作的？”

## B2. Theory ↔ Code Comparison
“理论上的 RRF 和当前项目实现有什么差异？”

这是 v6 的重要差异化能力：Knowledge Evidence + Repository Evidence。

## B3. Failure / RAG Diagnosis
“为什么这次 Retrieval Recall 下降？”

## B4. Change Impact
“这个 PR 改了 Retriever，可能影响哪些模块和测试？”

## B5. Docs-Code Consistency
“README 里的运行流程和当前代码一致吗？”

要求：

- 不是只新增 Tool；
- 必须形成端到端用户任务；
- Evidence 必须可追溯；
- Evidence 不足时允许明确拒答 / 降级。

---

# 8. Phase C — Engineering Evaluation 2.0

## C1. Dataset

建议第一版：

- 12～20 cases；
- public Dev；
- 至少覆盖：
  - repo understanding
  - theory-code comparison
  - change impact
  - docs-code consistency / diagnosis

真实 repo：

- `my_agent` 可作为可解释 fixture；
- 至少再引入 1 个 pinned 外部 RAG / Agent 开源仓库；
- 不只在 Spring Petclinic 上证明最终产品能力。

## C2. Metrics

核心：

- Task Success；
- Evidence Coverage；
- Evidence Correctness；
- Required Tool Coverage；
- Wrong / Forbidden Tool Rate；
- Answer Grounding。

成本：

- LLM Calls；
- Tool Calls；
- Latency；
- Token usage（稳定可取时）。

## C3. Core Agent Completion Gate

只有满足以下条件，才认为“基本 Agent 系统差不多做好”：

1. 至少 4 类真实 AI Engineering task 可端到端完成；
2. Knowledge Evidence 与 Repo Evidence 可组合；
3. Change / Test evidence 至少形成一个完整垂直切片；
4. 有 12～20 case 的 Engineering benchmark；
5. 主要失败模式能解释；
6. Safe Trace / failure semantics 稳定；
7. Demo 不要求用户理解内部 Basic/Agentic/Tool 三种模式才能使用。

到这里：

**Core Agent System = COMPLETE**

---

# 9. Core 完成后：选择性吸收 EvoAgent 精华

高级能力采用：

- **Architecture-ready**
- **Feature-later**

技术广度是校招价值的一部分，因此高级能力不必全部满足生产业务刚需；但必须是轻量、可演示、可对比，不能成为 Core 主链路强依赖。

## Advanced A — Runtime Lifecycle

候选：

- `run_id`
- status
- step summary
- structured failure
- started / finished metadata

不要默认上 DB queue、Temporal、distributed scheduler。

## Advanced B — Specialist / Critic Multi-Agent

推荐最小实验：

`Single Agent`
vs
`Specialist + Critic`

必须 A/B：

- task success；
- evidence coverage；
- calls；
- latency；
- failure rate。

允许负结论，不要求 Multi-Agent 必须晋级默认路径。

## Advanced C — Lightweight Checkpoint / Resume

只有真实长任务 / 中断恢复需求出现后做。

第一版可以是：

- serializable run state；
- SQLite / JSON；
- interrupted → resume。

## Advanced D — Controlled Evolution

推荐学习 EvoAgent 的：

`Failure`
→ `Failure Category`
→ `Candidate Improvement`
→ `Offline Evaluation`
→ `Human Promotion`

候选 improvement：

- prompt candidate；
- tool policy candidate；
- retrieval policy candidate；
- skill candidate。

禁止：

- 自动修改生产代码并 push；
- 无评测 self-update；
- 在线无控制策略漂移。

## Advanced E — Memory（条件）

G8 已证明 recent context 有局部收益。

Long-term Memory 只有长会话任务明确受限时才做。

顺序：

1. structured summary；
2. relevant memory retrieval；
3. persistent memory。

不默认建设 Vector Memory。

## Advanced F — MCP / External Integration（可选广度项）

若 Core 完成且时间充足，可做 MCP-compatible adapter 或接入一个外部 MCP capability。

目的是展示 Agent 工具生态理解，不重写核心 Runtime。

---

# 10. 明确不做 / 默认不做

除非出现新证据，否则不进入主线：

- 每个 repo 默认全量 Vector DB；
- 万能 Coding Agent / 自动代码修改器；
- 自动 commit / push；
- 多 Agent swarm；
- 无边界长期 Memory；
- 在线 self-modifying Agent；
- Kafka；
- Kubernetes；
- 微服务拆分；
- 多租户 IAM；
- 大规模并发 Agent 平台；
- 为了架构图增加数据库 / Queue；
- GraphRAG 仅因“前沿”而加入。

---

# 11. 前端策略

前端当前足够支撑开发与 Demo。

原则：

> 左边管会话，右边管聊天；Answer / Evidence / Execution 分层展示。

后续只在核心任务需要时调整，例如：

- Change Impact Report；
- Diff evidence；
- Test recommendation；
- Multi-Agent comparison。

最终产品可逐步收敛为统一 Ask / Analyze 入口，由 Runtime 内部选择 evidence path。

---

# 12. Study Note 规则

从 v6 起：

> **每个重要后端能力任务必须有学习沉淀，Study Note 是验收项。**

至少回答：

1. 技术解决什么问题；
2. 基础原理；
3. 为什么适合 / 不适合当前项目；
4. 项目代码链路；
5. 数据结构；
6. failure / trade-off；
7. 实验结果；
8. 面试怎么讲；
9. 常见追问。

不要求每个 MICRO / typo fix 都新建文档。

---

# 13. 推荐执行顺序

```text
CURRENT
2603ab7
G9-RELIABILITY-01 CLOSED
        ↓
A1 Git / Change Evidence
        ↓
A2 Test Evidence
        ↓
B1/B2
Implementation + Theory↔Code
        ↓
B3/B4/B5
Diagnosis + Change Impact + Docs-Code
        ↓
C Engineering Evaluation 2.0
        ↓
CORE AGENT COMPLETE
        ↓
选择性吸收 EvoAgent
        ↓
Specialist/Critic A-B
Checkpoint/Resume（条件）
Controlled Evolution（推荐）
Memory（条件）
MCP adapter（可选）
        ↓
Release 2.0 Evaluation / Demo / Freeze
```

---

# 14. Release 2.0 最终交付形态

正式目标：

# Evidence-Grounded AI Engineering Agent

最终 Demo 至少展示：

### Demo 1 — Knowledge
技术问题 → Knowledge RAG → grounded answer。

### Demo 2 — Repository
项目问题 → code_search / read_context → code evidence。

### Demo 3 — Cross-source
理论问题 + 当前实现 → knowledge + code → comparison。

### Demo 4 — Change
Git diff → impact → related code / tests → report。

### Demo 5 — Failure
Provider / evidence failure → structured safe failure。

### Demo 6 — Advanced（若完成）
Single vs Specialist/Critic，或 checkpoint/resume，或 controlled evolution。

---

# 15. 校招叙事

推荐介绍：

> 我做的不是单纯知识库问答，而是一个面向 AI/RAG/Agent 研发场景的 Evidence-Grounded Engineering Agent。长期稳定的 AI 技术知识使用共享 RAG 索引，临时代码仓库默认通过代码、Git 和测试工具按需取证，因此不会给每个仓库重新建立向量数据库。上层 Agent 根据任务动态组合 Knowledge Evidence 与 Repository Evidence，并通过 Verifier 和结构化失败边界保证回答可追溯。项目同时有 Retrieval、Agentic RAG、Tool Agent、Context 与 Engineering Task 的系统评测。Core 完成后，再用 A/B 探索 Multi-Agent、Checkpoint 和 Controlled Evolution，而不是把前沿模块无条件堆进主链路。

---

# 16. v6 治理规则

今后所有新需求先问：

### Q1. 是否增强 Core AI Engineering Task？
如果是，优先做。

### Q2. 是否展示重要 Agent 技术广度？
如果业务非必须但校招价值高，可在 Core 完成后做 lightweight slice。

### Q3. 是否可被实验 / case 验证？
如果只有“这个词很火”，没有任务、baseline 或验证方式，默认不进入主线。

最终原则：

> **Core 先完整，Advanced 再前沿；Evidence 是主轴，EvoAgent 是参考，不是需求清单。**
