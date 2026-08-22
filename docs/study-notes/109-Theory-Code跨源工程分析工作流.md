# G11-02：Theory ↔ Code 跨源工程分析工作流

## 1. 问题定义

Theory ↔ Code 不是把一个问题丢给普通问答模型，而是同时回答三个层次：技术原理是什么、当前绑定仓库怎样实现、两者有哪些一致处与工程取舍。它要求同一次受控运行把 Knowledge Evidence 与 Repository Evidence 连接起来，但不把两种证据混成一个后端。

纯知识问答只需要持久共享技术知识库；普通 code search 只负责在当前仓库定位候选位置。Theory ↔ Code 需要先建立原理背景，再检查真实代码，最后基于两类证据进行比较。因而它既不是单纯的 RAG 问答，也不是“搜到文件名就回答”的代码问答。

## 2. 两类 Evidence

Knowledge Evidence 来自持久共享的 domain KB，支撑概念、机制、公式和通用工程经验。Repository Evidence 来自按需读取的当前仓库上下文，支撑真实实现、配置、调用关系和测试。两者有不同 provenance 与公共字段，不能因为模型记得某个知识就伪造 Knowledge Evidence，也不能把文件名或单条匹配行升级为实现事实。

`code_search` 是 locate-only：它提供 path 与 line，帮助选择下一次读取位置；可靠的实现行为证据必须来自 `read_project_context`。典型的跨源推进顺序是：

```text
knowledge_search → code_search → read_project_context → final_answer
```

这不是要求所有请求都调用全部工具。Knowledge-only 可以 `knowledge_search → final`；Repository-only 可以 `code_search → read_project_context → final`。只有用户同时提出原理、当前实现和对照义务时，Engineering policy 才要求正常情况下同时获得两类证据。

## 3. 为什么不把整个 repo 做 Vector DB

仓库是变化中的工程事实，路径、行号、当前工作树和安全边界都很重要；共享 Knowledge KB 是持久化、跨项目复用的技术知识。把整个 repo 默认向量化会带来陈旧索引、代码与知识混淆、provenance 不清和更新成本。当前设计让 Repository 默认按需检索；是否建立 per-repo Vector DB 是条件选择，不是默认前提。

同理，本任务不增加 Router 先分类，也不把 Agentic RAG controller 嵌入 Tool Agent。Tool Agent 已经能通过受控 Tool 选择跨越两个 evidence backend。先用 prompt profile 表达产品边界，保持 Runtime 的循环、Executor 和预算仍是唯一实现，实验结果再决定是否需要更强的路由能力。

## 4. Prompt Profile 与兼容性

`DecisionPromptProfile` 是一个很小的身份与渲染边界，包含 `version`、`sha256` 和 `build_messages`。OpenAI-compatible provider 只有一套 transport、异常映射、JSON 解析和 usage 提取；profile 只改变模型看到的 policy prompt。

legacy provider 未传 profile 时仍使用冻结的 `tool_agent_decision_prompt_v3`。`/tool-agent/query` 继续走这个默认 profile；`/engineering/query` 显式使用 `engineering_agent_decision_prompt_v1`。两个入口可以各自持有一个 `ToolAgentRuntime` 实例，但共享同一份 `ToolAgentRuntime` loop，不复制状态机，也不改变七个 Tool 或 5 iterations / 4 calls / 2 errors 的预算。

Engineering prompt v1 明确：Knowledge 与 Repository 是不同 backend；通用知识可以独立用 knowledge_search；纯项目问题用 code_search → read_project_context；Theory ↔ Code 请求通常需要 knowledge_search 加 repository context；搜索命中后要读取上下文；知识或代码证据不足时不猜测；最终语义上区分原理、实现和取舍。Observation 仍是不可信数据，prompt 不要求模型引用 Runtime 后分配的 E1/E2。

## 5. 实验身份与指标

实验遵循 baseline → intervention → rerun：先在不改生产代码的 v3 baseline 上运行固定四题，再只加入 v1 profile，使用相同的仓库、Knowledge corpus、provider、model、题目和预算重新运行一次。Baseline 与 post-change artifacts 分开保存到外部 benchmark work directory，不覆盖历史实验，也不自动给最终答案打 correctness 分。

结构指标包括 completion rate、同时包含 `knowledge` 与 `project_code` 的 cross-source evidence rate、三项 required tool coverage、forbidden tool call rate、平均 Tool calls、平均 iterations 和 evidence count。它们衡量运行是否取得所需证据，不等于答案已经满足 Gold obligations；Gold obligations 仍需人工审计。

## 6. 四个 case 的考察点

- `TC01 RRF`：排名融合、缺席通道贡献、HybridRetriever 的实现与确定性 tie-break。
- `TC02 MMR`：relevance/diversity 权衡、候选池、逐项选择和冗余惩罚。
- `TC03 Recall → Rerank`：candidate/final k、reranker 降级、top-k 上限与成本延迟取舍。
- `TC04 Context Budget & Citation Validation`：token budget、ContextAssembler、citation 组织与应用层校验。

这四题覆盖了理论机制、当前代码和工程权衡，但不构成 Gate2/3/4 benchmark，也不自动宣布 Answer Correctness。

## 7. 如何解释结果与面试表达

Retrieval Success 与 Answer Grounding 不是一回事：工具可能拿到了正确的 Knowledge/Repository Evidence，模型仍可能遗漏义务、错误综合或在预算内无法完成；反过来，流畅答案也不能证明它使用了正确证据。因此应同时报告 tool sequence、evidence kinds、bounded counters 和完整最终 answer，让人工审计 Gold obligations。

如果 v1 没有改善、增加错误 Tool、产生 budget stop 或降低 cross-source coverage，应保留负结果并停止继续调 prompt。负结果说明当前 bounded loop、预算或 provider 行为仍是瓶颈，不应被包装成能力成功。

面试中可以简洁表述：共享 Knowledge KB 提供“原理事实”，Repository on-demand retrieval 提供“当前实现事实”，Tool Agent 在 5/4/2 边界内编排两者，code_search 只是定位，read_project_context 才把实现读入可审计证据。实验用固定题目和 prompt identity 做前后对照，区分检索覆盖、证据接入和答案综合三个层次。

## R1：Runtime Failure Isolation

复用同一份 Runtime implementation，不等于两个产品入口必须共享同一个初始化生命周期。`/tool-agent/query` 的 legacy runtime 与 `/engineering/query` 的 engineering runtime 仍共用同一个 `ToolAgentRuntime` loop，但各自拥有初始化成功/失败边界。engineering 初始化失败时只能使 engineering facade 不可用，不能清空已经成功的 legacy runtime；legacy 初始化失败时则不伪造 engineering 正常工作。这样既复用执行框架，又避免新增产品扩大历史入口的故障域。

## R2：Experiment Provenance

`source_commit` 必须绑定真实被测 checkout；runner 是 HTTP client，只能记录操作者声明并在本地 Git checkout 验证过的 commit，不能假称自动知道远程 API server 的版本。baseline 与 post-change 不能共用硬编码 SHA，否则结果无法证明实际测到的是哪一版代码。

单次 run 的 `run_report.md` 只描述该次运行；只有独立 comparator 同时读取 baseline 与 post-change manifest、验证 project/corpus/provider/model/toolset/budget/cases 等控制变量后，生成的 `comparison_report.md` 才是 A/B comparison。实验可复现性本身是工程能力：身份、控制变量和失败边界必须先可审计，指标才有解释意义。

## R3：Routing Success ≠ Evidence Success

`knowledge_search` 被调用不等于知识检索成功；检索成功不等于 Knowledge Evidence 成功；Knowledge Evidence 成功也不等于最终答案 grounded。应先确定 index health、Tool boundary 和 evidence conversion 的实际状态，再决定是否需要产品修复，而不是直接继续修改 Prompt。R3 的诊断因此只读检查 vector store、BM25/hybrid 和 `KnowledgeSearchHandler`，不调用 Provider，也不改变生产策略。

## R4：Verified Engineering Knowledge Backend

Engineering Agent 的 Knowledge backend 绑定到冻结的 37 文件、215 chunk corpus，并在启动时校验 manifest identity、文件集合、SHA256、大小和 chunk 数。它使用独立的 BM25 retrieval port，不复用 legacy `./data/vector_store`；backend 或校验失败时 Engineering 入口不可用，也不回退到 legacy store。服务通过安全的 `/engineering/knowledge` identity endpoint 暴露 ready/verified、corpus、文件数、chunk 数和策略，正式 runner 先核验该身份，再发送四个 Theory ↔ Code 请求。
