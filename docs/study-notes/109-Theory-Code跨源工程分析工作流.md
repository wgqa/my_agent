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

legacy provider 未传 profile 时仍使用冻结的 `tool_agent_decision_prompt_v3`。`/tool-agent/query` 继续走这个默认 profile；R4 的 `/engineering/query` 使用 `engineering_agent_decision_prompt_v1`，R5 正式入口升级为 v2。两个入口可以各自持有一个 `ToolAgentRuntime` 实例，但共享同一份 `ToolAgentRuntime` loop，不复制状态机，也不改变七个 Tool 或 5 iterations / 4 calls / 2 errors 的预算。

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

## R5：Budget-Aware Agent Control

Hard Budget 与 Model Awareness 是两件事：Runtime 仍唯一拥有并强制执行 5 iterations / 4 Tool calls / 2 Tool errors，但 Engineering Prompt v2 在每次 Decision 的 system message 中获得 Runtime 计算的只读 `DecisionControlState`。它属于 trusted control state，不是 `DecisionContextItem` 中的不可信 Tool Observation；模型可以知道剩余能力，却不能修改预算，也不能让 API request 覆盖它。

v2 只提供停止指导：`tool_call_allowed=false` 或 `must_terminate=true` 时只能输出 final/refuse；Runtime 原有 hard stop 仍保留，因此恶意 Tool call 也不会越过边界。legacy `tool_agent_decision_prompt_v3` 完全不变，v1 Engineering profile 与 R4 artifact 继续保留用于历史审计；R5 正式 A/B 只使用新的 Engineering v2 identity，其他 checkout、corpus、题目、provider、model 和预算保持不变。

这属于 Agent orchestration 的控制协议，而不是放大预算或增加 parse retry 的 Prompt 技巧。实验结果需同时观察 completed、budget stop、parse failure、evidence coverage、calls、iterations 与 latency；不能仅凭完成率宣布能力成功。

## R6：Structured Action Reliability

JSON mode 只要求 Provider 返回语法上的 JSON，并不保证 Action 的字段集合、Tool 名称或 arguments schema 正确。Strict parser 因而继续拒绝空输出、markdown fence、前后 prose、duplicate key、未知 action、未知 Tool 和错误参数；通过放宽 acceptance boundary 来提高完成率，会把不可审计的脏输出伪装成合法动作。

R6 在 strict parse 之后增加安全 taxonomy，至少区分 `OUTPUT_TRUNCATED`、JSON syntax、Action semantic shape、unknown tool 和 arguments schema。syntax failure 与 semantic action failure 都保留公共 `ACTION_PARSE_FAILED`，但内部分类让诊断和实验指标知道失败发生在哪一层。Provider 读取 `finish_reason`：只有在严格解析失败时，`length` 才优先标记为 `OUTPUT_TRUNCATED`；如果 JSON 恰好完整且 parser 成功，仍以成功为准。

Engineering v2 获得最多一次 bounded structured-action repair。它不是 network retry、Provider retry、Tool retry 或 Runtime retry，而是同一个 Decision 的第二次受控模型调用：复用原 system policy、user question、已有 trusted control state 和不可信 Observation context，再追加独立的 `engineering_action_repair_prompt_v1` 指令。Repair 不接收、不写入、不持久化 malformed raw output，因此 trace、API response、metadata 和 artifact 都只保存 category、bool、小整数等安全字段。Repair 成功后仍必须经过 Registry、schema validation、budget、duplicate detection 和 ToolExecutor；`must_terminate=true` 时产生 tool_call 也会被 Runtime 硬边界拒绝。

Legacy v3 默认保持 0 次 repair，避免默默改变历史 `/tool-agent/query` 行为；Engineering v2 默认最多 1 次。R6 保持 `DECISION_MAX_OUTPUT_TOKENS=600`，因为在没有确认 baseline 失败确由 truncation 导致前，不应盲目增加输出预算。修复可能提升 completion，但会增加 Provider call、token、latency 和成本，所以必须同时报告 repair attempt/success rate、provider calls、parse failures、tool calls、iterations、cross-source evidence 和 evidence count，不能只看完成率。

## R7：Evidence Sufficiency & Grounded Finalization

Retrieval success 不等于 evidence relevance，tool called 不等于 evidence sufficient，答案正确也不等于答案 grounded。Engineering v3 因此把最终回答前的证据充分性判断写入通用 policy：当问题涉及当前实现、源码行为、算法细节、调用关系、配置行为或返回字段时，`project_code` source evidence 优先于 README、study note、design doc 和历史文档；文档可以补充设计意图，但不能证明当前代码实际如何执行。

`code_search` 是 Locate，不是 Read。搜索应从用户问题提取 method、variable、config key、operator 等定义行为的 identifier；多个命中时优先 function/method body 和 behavior-defining statement。`read_project_context` 的 bounded window 必须真正包含回答所需的分支、公式、参数、fallback、调用关系或返回字段；调用过工具一次，或只读到 class header、loop 开头、调用点或文档，并不构成充分证据。仍有预算时继续读取更相关的代码位置，没有预算时缩小 claim 并明确未验证部分。

Theory claim 需要 Knowledge Evidence 的语义支持。知识检索优先使用 mechanism、algorithm、evaluation concept 和 engineering tradeoff 等问题术语，避免把 repo symbol 或 path 混入理论查询；知识证据不能支持的内容不能由 model prior 补成“已验证事实”。这种边界把 Evidence Sufficiency 与 Hallucination 直接连接起来：证据不足时，模型必须减少声称，而不是用熟悉的先验补齐当前实现。对于 verifier/validator，只能声称 evidence 实际展示的能力；identity 或 existence check 不能被扩展成 semantic support validation。

Finalization 的 grounding checklist 只要求模型做结果判断，不要求输出 CoT：识别用户的子问题；逐个检查当前实现 claim 是否有 Project Code Evidence；逐个检查 theory claim 是否有 Knowledge Evidence；确认源码问题不是只有 `project_doc`；确认 evidence 窗口实际展示了声称的公式、分支、参数、fallback、调用关系或返回字段。若检查失败且仍有 Tool budget，继续 Tool；若没有预算，输出缩小后的结论并标明未验证边界。Grounded Finalization 是 Evidence-Grounded Agent 的核心能力，因为它把“拿到证据”与“只声称证据真正支持的内容”连接起来。R7 不增加 Tool、不扩大 5/4/2、不改变 read window，也不引入 LLM-as-Judge。

## R7 Formal Result：Negative Result & Stop Rule

R7 的固定 run 是 `g11-02-r7-evidence-grounded-20260823-204821`，绑定 `source_commit = fc2679a4af75ae1fcb20ea787dba3224492f9f23`、`prompt = engineering_agent_decision_prompt_v3`。本次结果为：4/4 completed，final parse failure = 0，source-code cross-source = 3/4，required tool coverage = 100%，forbidden tool = 0，repair attempted/succeeded = 1/1，initial parse category = `OUTPUT_TRUNCATED`。R7 因而没有改善 R6 已观测的 3/4 source-code cross-source：`R7 = negative / inconclusive for grounding improvement`。

### 人工审计结论

- TC01：Project Code window insufficient；implementation claims 超过读取 Evidence。
- TC02：window 停在 MMR loop 前；最终公式与真实实现不完全一致。
- TC03：Project Code sufficient；Knowledge Evidence relevance weak。
- TC04：仍只有 `project_doc`，没有 Pipeline source code；存在 validator capability overclaim。

这次审计明确了三个不能混淆的判断：

- `correct answer != grounded answer`
- `project_code presence != sufficient project evidence`
- `Tool coverage != claim coverage`

### 为什么负结果仍有价值

R7 把“模型回答正确”与“回答中的 claim 被当前证据支持”分开，并暴露了窗口位置、证据类型和 claim 级支持之间的缺口。它证明了 v3 的 grounding checklist 在固定四题上没有带来可观测的 source-code cross-source 改善，也保留了可复核的 negative result、人工审计记录和完整 artifact provenance。这个结果不是 Prompt 失败的泛化结论，而是对固定 TC01-TC04、固定预算、固定工具和固定 Knowledge backend 的受控观测。

因此不继续针对 TC01-TC04 做 Prompt tuning。继续在同一组 case 上调 Prompt 会把 benchmark 适配误认为能力提升，放大 benchmark overfitting 风险，同时无法解决 evidence relevance、window sufficiency 和 claim-level grounding 的跨任务问题。Production 应恢复最后一个有实证支持的 baseline，而不是把未证明改善的实验 prompt 升级为默认值。

### Production baseline、资产与 stop rule

`/engineering/query` 恢复使用 `ENGINEERING_DECISION_PROMPT_V2_PROFILE`：`engineering_agent_decision_prompt_v2`，SHA-256 为 `14a1cbbe3dec951b7723bf5a7578e5f1aabc96639ac62b984976cecb5f53a107`。v2 已通过 Formal R6（4/4 completed、0 final parse failure）；v3 Formal R7 未证明 grounding 指标提升，因此保留为实验结果，不提升为 production default。

R7 不删除任何实验身份或资产：Engineering v3 template、v3 SHA、v3 tests、runner v3 identity、Study Note R7 和 R7 artifact provenance 均保留。R7 artifact 位于外部 benchmark work directory，run manifest 继续记录 source commit、prompt/repair identity、Knowledge backend、budget 和安全记录。Repair matrix 继续为 Legacy = 0、Engineering v2 = 1、Engineering v3 = 1；v3 identity 仍可构造，历史 runner 仍接受 v3。

G11-02 到此关闭。冻结 v2/v3/Repair Prompt、Strict Parser、Tool implementations、Knowledge backend、5/4/2 budget、7-tool registry、600 max output、四个 runner case 和 Gold obligations；不得开始 R8。Evidence Sufficiency debt 应跨 task family 重新验证后再设计系统机制，统一带入 G12 Engineering Evaluation 2.0。
