# my_agent 技术债 / 重构点 / 改进点清单

> 唯一维护位置：仓库内的 `docs/technical_debt.md`。工作区原来的 `technical_debt.md` 仅保留入口链接，避免维护两份内容。
>
> 目的：把我们在项目回顾、架构讨论、实验复盘和源码核对过程中提到的技术债、重构候选与能力缺口集中记录，避免后续继续讨论时“注意力稀释”。
>
> 当前原则：**先完成源码级学习，再基于证据做架构决策；不因为“现代”“流行”“看起来更高级”就改。**
>
> 当前主线：`项目整体回顾 → 技术债清单 → 源码级系统学习 → 真正吃透当前实现 → 基于证据做架构/技术债决策 → 新开发`

---

## 最近处理记录

2026-10-03：TD-TOOL-02 范围搜索候选已实现并验证，**默认未晋升、继续 v5**。候选加入文件/目录 scope 与真正的结果截断，局部 **193 passed / 7 skipped**；两仓库 8 题配对、16 个真实用户请求中，scope 使用 0/8 次搜索，取证路径及调用数均与旧版相同，未证明问答收益。负结果、原版及候选快照保留；见 [范围搜索验证](validation/2026-10-03-source-search-v6.md)。这不是新功能已完成上线，也没有关闭整个取证债务。

2026-10-02：项目所有者授权分切片处理简单技术债。已完成的清理切片如下；大项的原有状态与冻结评测结论继续保留。

| 关联债务 | 本次处理 | 状态 |
|---|---|---|
| TD-RUNTIME-01 的 Observability 维护切片 | SSE v1/v2 共用事件编码、后台 facade 调用、取消转发和结束回调；移除两份重复 worker，保留各自的 presentation 与公开事件协议 | 专项 27 passed，离线核心与真实 SSE smoke 通过；核心 Runtime 复杂度债未关闭 |
| TD-CLEAN-02 的文档入口切片 | 本清单迁入 Git 仓库，README 增加入口，工作区旧路径改为链接 | 迁移完成；历史 Gate/Repair 文档归档债未关闭 |
| TD-RUNTIME-01 的共享文件分类切片 | 分类规则迁入 `core/tool_agent/project_files.py`，搜索与 Runtime 复用同一实现；保留工具和旧评测导入入口 | 3270 个路径与工具输出前后一致；离线回归无失败，详细口径见 TD-RUNTIME-01；整体 Runtime 债未关闭 |
| TD-CI-01 的关键回归覆盖切片 | 现有离线 job 补入函数读取、文件分类、工具身份和连接生命周期回归，共新增 4 个测试文件 | 清单遗漏已修复；本次相关 5 个文件局部验证 70 passed，完整 CI job 未运行 |
| TD-STORE-01 的连接生命周期切片 | 所有 CRUD 提交/回滚后关闭连接，初始化异常也关闭；第二条消息失败时整轮回滚 | 13 项新增生命周期回归及既有会话回归通过；初始化频率与版本检查顺序仍开放 |
| TD-CLEAN-02 的当前文档对齐切片 | README 主会话、legacy Demo、Conversation API 与运行手册对齐源码；历史全量结果按切片标注 | 已完成源码核对，按项目所有者要求不测试；历史文档归档债仍开放 |

初次整理只核对源码和差异，未运行测试。随后项目所有者授权测试并补充 DeepSeek 额度：专项 27 passed，CI 离线核心 670 passed / 5 skipped，Full App smoke 通过；真实 DeepSeek 源码问答、知识问答、两版 SSE 与知识多轮会话/重启恢复可运行。纯计算在 Engineering 主链被引用校验误拒答，登记到 TD-PLAN-01 / TD-VERIFY-02，尚未修复。详细范围与证据见 [系统验证记录](validation/2026-10-02-sse-cleanup.md)。

Jev 判定证据要求已在 2026-10-02 暂缓，仍使用原有关键词路由。历史接入见 [归档记录](archive/jev_evidence_routing/design.md)，不属于当前待测试产品能力。

同日，项目所有者授权扩大测试范围并基于结果判断重构必要性。最终全量 2658 passed / 6 skipped，新项目与边界检查 42/42；首轮 28 项真实任务链路有效，但逐条源码与引用审查为 10 PASS / 12 PARTIAL / 6 FAIL（含 4 项预期拒答；不是独立验收）。另有 2 项单独标识的覆盖/根因诊断，总计 30 次请求。详细问题、失败过程和拟议重构顺序见 [系统覆盖与迁移评估](validation/2026-10-02-system-assessment.md)。本轮未改 Production 策略，未宣布产品质量 blocker 关闭。

| 本轮复现 | 关联债务 | 处置与剩余工作 |
|---|---|---|
| 纯计算 Planner 跨字段非法，触发检索后误拒答；工程任务与知识检索计划错位 | TD-PLAN-01 / TD-ROUTER-01 / TD-VERIFY-02 | 单一工程任务契约替代入口多处任务语义判断，明确计算结果、知识和仓库材料分别支持什么 |
| 宽搜索被 examples 占满；长函数窗截断；测试问题搜索错误类型；多轮读取类声明而非目标方法 | TD-TOOL-02 / TD-ROUTER-01 | 有界 Python 函数读取及续读切片已实施，5/4/2 不变；搜索与多轮对象定位继续开放，见下文验证 |
| 知识缺少 IDF 说明；合法 E-ID 不支持句子；BM25 空白/标点 token 可造成无关命中 | TD-RAG-01 / TD-PLAN-02 / TD-VERIFY-01 | 分清语料缺口、相关性和引用支持，先约束回答范围；tokenizer 候选不能覆盖冻结基线 |
| 新源码目录可绑定，但 Engineering 仍依赖固定 37 文档的 verified corpus | TD-RAG-01 / TD-ARCH-01 | 项目与知识配置解耦，冻结语料作为明确配置保留，新增领域经过独立评估 |

这些切片用来收敛已有职责，不再增加 Jev 判定器、第二个 Agent loop 或按题型逐项放行的 Guard 例外。新项目挂载已写成 [操作手册](project_mount_runbook.md)。

第一改进切片已完成：交付版全量 **2692 passed / 6 skipped**；8 题旧/新两轮共 32 次真实 DeepSeek 请求，保留首轮类声明回退负结果。最终新版所问行为 7 PASS / 1 PARTIAL，整份答案 5 PASS / 3 PARTIAL；长函数尾部关键分支获取明显改善，引用语义边界仍开放。详细范围、代价、混杂因素和复跑材料见 [函数读取验证](validation/2026-10-02-source-reading-v2.md)。总体任务/执行契约留待下一步讨论，尚未实施。

后续已在项目所有者授权下形成 [Task / Evidence / Execution Contract v2 草案](design/engineering_task_execution_contract_v2.md)：关联 TD-ARCH-01 / TD-RUNTIME-01 / TD-PLAN-01 / TD-VERIFY-01/02 / GAP-CAP-01，保留单一循环，定义默认 policy、逐项完成、精确来源与执行凭据，以及 21 个实施前反例。状态为 **DRAFT / 待评审 / 代码未实施**；项目所有者已明确将其作为长期设计目标，近期暂缓，当前继续处理小范围维护债务。技术债未因此关闭，扩容与编辑能力未启用。

同日后续只读审查新增 `TD-CI-01`（近期关键回归未进入 CI）、`TD-STORE-01`（SQLite 连接关闭与初始化边界）、`TD-STORE-02`（长会话全量读取）；审查时未实施，详细证据和验收范围见本文件末尾“近期维护审查”。随后项目所有者明确授权 CI 覆盖补齐 → SQLite 显式关闭 → README / 运行手册对齐三项维护，现已完成对应切片：前两项局部验证 **70 passed**，第三项仅核对源码、未测试；没有完整 CI job、全量回归或真实模型请求。长会话容量与语义质量改进继续单独评估。

---

## 0. 当前项目主链基线

当前 Engineering 主链：

```text
EngineeringAgentFacade
    ↓
UnifiedEngineeringRuntime
    ↓
Context Resolver
    ↓
resolved_input
    ├──→ Evidence Planner
    ├──→ Evidence Requirement Router
    ↓
Planned Knowledge Retrieval
    ↓
RetrievalSnapshot
    ↓
ToolAgentRuntime
    ↓
Decision → Tool → Observation → Decision
    ↓
Finalization Verifier
    ↓
Answer / Refuse
```

当前 ToolAgent 的模型调用方式：

```text
ToolAgentRuntime
    ↓
OpenAICompatibleAgentDecisionProvider
    ↓
Prompt Profile + Tool Specs + Runtime Control State + Context
    ↓
OpenAI Python SDK
    ↓
OpenAI-compatible Chat Completions API
    ↓
DeepSeek
```

当前不是 Provider-native Function Calling：

```text
Tool Specs
    ↓
写进 Prompt
    ↓
response_format={"type":"json_object"}
    ↓
LLM 在 message.content 里返回 JSON Action
    ↓
ActionParser
    ↓
ToolCallAction / FinalAnswerAction / RefuseAction
```

---

# 一、用户明确标记 / 已确认需要保留的技术债

## TD-RAG-01：RAG 参数与泛化验证不足

### 当前状态

当前已经有正式实验支撑：

- Dense / BM25 / Hybrid 对比
- Fixed / Recursive chunking 对比
- tokenizer-aligned chunk budget
- query decomposition
- RRF merge

当前冻结技术语料 benchmark 中，BM25 表现最好，因此 Engineering Knowledge hot path 当前使用 BM25。

但下面这些没有做过系统、受控的正式实验：

- `chunk_size` sweep
- `chunk_overlap` sweep
- 多 embedding 模型正式 benchmark
- 跨语料 / 跨领域泛化验证
- BM25 `k1 / b` 系统 sweep
- 更完整的 `top_k` sweep

### 风险

当前“BM25 最强”的结论只对当前 frozen technical corpus 有效。

不能直接推导成：

```text
BM25 永远优于 Dense / Hybrid
```

也不能推导成：

```text
512 / 64 就是最佳 chunk 参数
```

### 为什么现在不改

当前没有证据证明参数调整一定能提升产品结果。

继续无目标调参容易重新回到“实验工程膨胀 > 产品能力增长”。

### 候选改进

后续做控制变量实验：

```text
Chunk Size
Chunk Overlap
Embedding Model
Corpus Domain
Top-K
BM25 k1 / b
```

优先级应由真实失败案例触发，而不是为了“实验完整度”而实验。

### 验证方法

至少观察：

- Hit@K
- Recall
- MRR
- nDCG
- Product task success
- latency
- token / cost
- failure mode

### 状态

**OPEN / 中优先级**

### 面试表达

> 当前系统不是默认采用向量检索，而是通过冻结技术语料 benchmark 对 Dense、BM25、Hybrid 做过对比后选择 BM25 作为产品主路径。后续仍保留 chunk、embedding 和跨语料泛化验证作为技术债，避免把单一 benchmark 的结论过度泛化。

---

## TD-RAG-02：Dense / Hybrid 没有进入真实 Product Hot Path

### 当前状态

当前 Engineering Knowledge backend 的产品主路径是 BM25-only。

项目历史上已经实现 / 验证过：Dense Retrieval、BM25、Hybrid Retrieval、RRF、Embedding Pipeline。

### 问题

存在一种可能：

```text
明显 lexical mismatch
→ BM25 找不到
→ Dense / Hybrid 其实能救回来
```

当前真实产品链没有一个明确、受控的 semantic rescue 路径。

### 为什么现在不改

不能因为“向量数据库更现代”就重新接回 Dense / Hybrid。必须证明真实失败案例能被 bounded semantic rescue 稳定修复。

### 候选设计

```text
BM25
    ↓ no / weak result
Dense or Hybrid rescue
    ↓
最多 1 次
```

概念上也可收敛为：

```text
knowledge_search(query, strategy="bm25|dense|hybrid")
```

但这只是候选设计，不是当前实现。

### 验证方法

A/B：

```text
A：BM25-only
B：BM25 + bounded semantic rescue
```

比较 task success、retrieval coverage、调用次数、latency、cost、noise。

### 状态

**OPEN / 中优先级**

### 面试表达

> Dense / Hybrid 并不是没做，而是当前 benchmark 下 BM25 更强，所以产品没有强行引入向量路径。Dense / Hybrid 作为 lexical mismatch 的 bounded rescue 候选保留，需要通过真实失败集 A/B 后再进入 hot path。

---

## TD-ARCH-01：重新评估“重控制链”与 Pi-style Minimal Agent 的边界

### 当前状态

当前强制链路：

```text
Context
→ Planner
→ Requirement Router
→ Planned Retrieval
→ ToolAgent
→ Verifier
→ Finalization Guard
```

这条链有历史原因。G11 / G12 曾暴露：premature finalization、Theory↔Code grounding 不完整、Change↔Test 单边证据、cross-file diagnosis 过早停止、Docs↔Code 一致性判断缺证据等问题，所以当时引入了 system-owned evidence floor。

### 当前问题

后来产品实验又暴露：

- Router 会 under-activate
- 扩大 Router 规则又可能 over-constrain
- 太多精力花在“规定 Agent 必须读什么”
- Knowledge Retrieval 被 front-load
- Unified path 中 `knowledge_search` 在 ToolAgent 内被 disabled
- 控制层开始承担越来越多语义判断

风险是：为了防止 Agent 出错，把太多本应由模型动态决定的语义问题搬到硬编码控制面。

### 应继续 system-owned 的硬约束

候选保留：Tool allowlist、预算、timeout/cancel、workspace 权限、duplicate call guard、trusted evidence identity、citation ID validity、tool input/output schema、未来 edit 后强制 test、明确安全边界。

### 应重新评估是否交还模型的语义决策

- 任务类型
- 是否必须 Knowledge Retrieval
- 需要读几个文件
- 是否跨文件
- 下一步该查什么 evidence
- 是否真的需要 Theory↔Code 双侧证据
- Planner 是否每次都 mandatory
- Requirement Router 是否必须成为 mandatory stage

### 候选实验

```text
A：Current Heavy Control Path
B：Lean ToolAgent + Rich Tools + Minimal Hard Guards
```

不要先删除现有路径。

### 比较指标

end-to-end task success、grounding quality、false refusal、premature finalization、tool calls、LLM calls、token、latency、failure categories、implementation complexity、maintainability。

### 状态

**OPEN / 高优先级架构债**

### 面试表达

> 项目早期通过系统级 evidence requirement 解决了 prompt-only 无法阻止 premature finalization 的问题；后续产品实验又发现 lexical router 会产生 under/over-constraint。因此下一阶段不是简单删除 Guard，而是区分 hard invariant 与 semantic reasoning，通过 Heavy Path vs Lean Agent A/B 决定 Planner、Router、Verifier 哪些应该 mandatory、哪些应该 optional。

---

# 二、Agent Tool Calling / Function Calling 相关重构候选

## TD-AGENT-01：自定义 Action Protocol 与 Provider-native Function Calling 重叠

### 当前状态

当前 ToolAgent 没有使用：

```python
tools=[...]
tool_choice=...
message.tool_calls
```

当前使用：

```python
chat.completions.create(
    messages=...,
    response_format={"type": "json_object"},
)
```

然后要求 LLM 在 `message.content` 里输出：

```json
{
  "action": "tool_call",
  "tool_name": "...",
  "arguments": {}
}
```

之后由我们自己：

```text
ActionParser
→ Registry check
→ JSON Schema
→ ToolCallAction
```

### 当前自定义协议额外承担

- ToolCall JSON 格式定义
- strict JSON parsing
- duplicate key rejection
- exact field set
- unknown tool classification
- argument schema validation
- output truncation classification
- one-shot Action repair

### 问题

其中一部分工作与 Provider-native Function / Tool Calling 能力重叠，即“模型如何表达我要调用哪个工具、参数是什么”。

### Function Calling 能替代什么

主要替代：

```text
Prompt 中手写 ToolCall JSON 格式
+
LLM 在 message.content 中模仿协议
+
ToolCall 相关 Action parsing
+
部分 parse-repair complexity
```

不会替代：ToolAgentRuntime、Agent Loop、Budget、Duplicate guard、ToolRegistry、ToolExecutor、权限、后端二次 schema 校验、Evidence Requirement、Finalization Verifier、Observation、Evidence extraction。

### 为什么现在不直接改

先完成源码级学习。另外 Function Calling 依赖 `Model + Provider API + SDK` 的真实支持程度，不能只因为“标准”就换。

### 候选 A/B

```text
A：JSON mode + Custom Action Protocol
B：Provider-native Tool Calling → adapter → existing ToolCallAction / Runtime
```

### 比较指标

- structured success rate
- parse failure rate
- repair call rate
- provider portability
- latency
- token cost
- code complexity
- debugging observability
- test complexity

### 状态

**OPEN / 高价值重构候选**

### 面试表达

> 当前项目为了 provider independence 和可控性自建了 Action Protocol，但其中 ToolCall 表达层与原生 Function Calling 存在重叠。后续计划保持 Runtime/Executor 不变，仅 A/B 替换 LLM→Host 的 ToolCall transport，比较稳定性和复杂度后决定是否迁移。

---

## TD-AGENT-02：ToolCall 与 FinalAnswer / Refuse 是否需要继续绑在同一 Action 协议

当前模型输出统一为：

```text
ToolCallAction
FinalAnswerAction
RefuseAction
```

优点是协议一致、易测试、failure taxonomy 统一、provider-independent。

但若未来采用原生 Function Calling，ToolCall 可以走 Provider-native channel，而 FinalAnswer / Refuse 仍可能走普通 assistant output。

候选：保留内部 `AgentAction` abstraction，但由 Provider adapter 把 native response 归一化成内部 Action，而不是要求所有东西都由 LLM 手写统一 JSON。

### 状态

**OPEN / 与 TD-AGENT-01 联动**

---

# 三、MCP 相关改进候选

## TD-MCP-01：当前不需要 MCP，但需要保留未来接入边界

### 当前状态

当前 7 个只读 Tool：

```text
calculator
code_search
read_project_context
knowledge_search
changed_files
git_diff
find_tests
```

都是本地 Python Tool：

```text
ToolRegistry
→ RegisteredTool
→ Local ToolHandler
→ handler.execute()
```

### 为什么当前没有 MCP

现在主要是一个 Python 应用、一个 Agent、Tool 大多同进程。如果为了 MCP 而 MCP，会变成：

```text
Local Handler
→ MCP Client
→ MCP Server
→ 原来的能力
```

用户能力不变，却增加 Client、Server、protocol、transport、discovery、serialization、connection lifecycle 和更多 failure mode，违反 `No Capability Delta, No Merge`。

### MCP 真正有价值的场景

- 多 Agent 共用 Tool
- Tool 独立进程
- GitHub / DB / Browser / IDE / third-party service
- 远程能力
- Tool 动态发现
- Tool 需要被多个 Host 复用

### 候选架构

保留现有 Tool abstraction，未来新增：

```text
LocalToolAdapter
MCPToolAdapter
```

而不是让 Runtime 感知 MCP。

### 状态

**DEFER / 当前不做**

### 面试表达

> MCP 不是 Function Calling 的替代品，它解决 Host→external capability 的标准化接入。当前 Tool 全是本地 Python capability，引入 MCP 没有 capability delta，因此延后；未来有跨进程、多 Agent、GitHub/DB/Browser 等外部能力时再以 adapter 方式接入。

---

# 四、当前最大能力缺口

## GAP-CAP-01：缺少真正的 Edit / Patch / Test / Repair Vertical Loop

### 当前状态

现在项目强项集中在 Retrieval、Evidence、Repo read、Git change read、Test discovery、Grounded answer、Runtime governance。

但真正用户可感知的工程闭环还不完整：

```text
理解仓库
→ 定位问题
→ 修改代码
→ 运行测试
→ 根据结果修复
→ 验证完成
```

当前主要还是 read-only Engineering Agent。

### 为什么高优先级

这直接决定项目从“会查代码、会回答”升级为“能完成真实工程任务”。相比继续增加 Router / Verifier 规则，能力增量更直接。

### 候选能力

- edit_file / apply_patch
- run_test
- run_build / compile
- inspect failure
- repair
- bounded retry
- before / after verification
- changed file summary

### 必须保留的硬约束

workspace boundary、writable path allowlist、patch size limit、command allowlist/sandbox、timeout、test budget、no destructive git operation、user-visible diff、rollback/failure state。

### 状态

**MISSING / 高优先级能力项**

### 面试表达

> 项目下一阶段重点不是再增加控制器，而是补齐真实软件工程 vertical loop，让 Agent 能从 repo investigation 走到 patch、test、repair 和 verification。

---

# 五、Planner 相关重构候选

## TD-PLAN-01：Planner 是否应该每次 mandatory

当前：

```text
resolved_input
→ Planner
→ QueryPlan
→ Planned Knowledge Retrieval
```

Planner 是 LLM driven，能做 direct/single/decomposed retrieval，并生成 2–3 subqueries。

Query decomposition 已做过正式实验，不能简单说 Planner 没用。但“有价值”不等于“每个请求都必须先跑”。尤其工程问题中，很多任务主要依赖 repo tools。

候选：Planner conditional、只用于 knowledge-heavy / complex retrieval、Lean Agent 自主调用 knowledge tool、Planner 作为 optional retrieval accelerator。

2026-10-02 扩展诊断新增确定证据：纯计算返回 `query_type=fact` / `action=no_retrieval`，而 QueryPlan 要求该 action 配 `unanswerable_or_no_retrieval`；Prompt 未明确此组合约束，导致 schema fallback。首轮中文/英文两题失败，单独根因诊断再现。问候的合法 no_retrieval 可以完成，因此不能概括为所有问题一定强制检索。与 TD-VERIFY-02 合并考虑任务契约，见 [本轮报告](validation/2026-10-02-system-assessment.md)。

### 状态

**RE-EVALUATE**

---

## TD-PLAN-02：Front-loaded Knowledge Retrieval 降低 Agent 动态检索自由度

### 当前状态

```text
Planner
→ Planned Retrieval
→ initial_context / initial_evidence
→ ToolAgent
```

然后：

```text
disabled_tools=("knowledge_search",)
```

ToolAgent 进入 loop 后不能再动态 knowledge_search。

### 问题

模型无法根据 repo investigation 后新发现的信息，再主动进行第二次知识检索。

### 候选方向

- 重新开放 bounded `knowledge_search`
- 仅允许 1 次 dynamic rescue
- Planner retrieval 保留为 seed，不再完全封死
- 或 Lean Agent 直接自己决定是否搜知识

### 风险

tool call 增多、循环膨胀、重复 retrieval、token/latency 上升。

### 状态

**OPEN / 与 TD-ARCH-01、TD-RAG-02 联动**

---

# 六、Requirement Router 相关技术债

## TD-ROUTER-01：Lexical Router 存在 under-activation

Fresh Set A 中 repo-specific task 经常没有拿到 repo evidence，Router vocabulary gap 是原因之一。

PRODUCT-REPAIR-23 的 bounded `_repo_navigation_intent()` 修复后，zero repo-tool 任务下降、repo evidence acquisition 提升、PASS/PARTIAL 改善，说明 lexical coverage 确实存在缺口。

### 状态

**OPEN / 已知 limitation**

---

## TD-ROUTER-02：扩大 Router 规则会 over-constrain

PRODUCT-REPAIR-25R 中 Router v2 扩大 requirement 后，部分场景 project evidence 提升，但已有场景从 completed 回归到 refused，因此没有 promote。

核心 trade-off：

```text
规则窄 → under-activate
规则宽 → over-constrain / false refusal
```

候选：Router optional、只负责 high-precision hard minimum、更多 evidence acquisition 决策交给 Agent。

### 状态

**OPEN / 高价值简化候选**

---

## TD-ROUTER-03：没有干净的 Lexical Router vs LLM Router 控制实验

历史讨论过 LLM self-reported requirement、deterministic classifier、hybrid typed requirement，但没有干净的 Lexical Router vs LLM Router 产品实验。

不为补实验矩阵而实验；只有 Router 成为主要瓶颈时再做。

### 状态

**DEFER / 条件触发**

---

# 七、Verifier / Evidence 相关技术债

## TD-VERIFY-01：当前 Verifier 是 structural，不是 semantic truth verifier

当前 Verifier 可以检查 evidence kind、identity、E-ID 是否存在、citation 合法性、required groups、distinct project code paths 数量。

但它不能真正证明：

```text
某一句自然语言 claim
是否被引用的 E1 在语义上支持
```

因此可能出现“合法 E1 + 错误 claim”的结构通过问题。

2026-10-02 的 C09 实际复现：词频源码判断正确，但 IDF / 长度归一化理论使用未包含该说明的 E1/E2；引用绑定为 VALID。C04/M01 也把 config.py 的 E6 用于 service.py 的调用结论。该能力边界有新的产品输出证据，仍未修复。

候选方向：先改善 answer↔evidence prompt、claim scope、source excerpt quality、tool acquisition quality、semantic grounding benchmark；若真实失败率仍高，再评估 semantic verifier，不直接堆第二个 Verifier LLM。

### 状态

**OPEN / 重要能力边界**

### 面试表达

> 当前 verifier deliberately 做 structural grounding，而不是 claim entailment。这样可控、低成本，但不等于证明语义真实性。项目明确记录这个边界，而不是把 citation validity 夸大成 hallucination solved。

---

## TD-VERIFY-02：Finalization Guard 可能承担过多任务语义

Guard 起源合理：模型不能自己降低证据门槛。但随着 requirement 类型增加，Guard 越来越依赖 Router 的语义判断。

2026-10-02 真实 smoke 新增一个明确复现：Engineering 主链的 `37 * 29` 已得到正确计算结果，知识检索和 requirement 均满足，却因已注入知识证据而要求 `[E#]`，最终以 `ANSWER_EVIDENCE_REFERENCE_MISSING` 拒答；旧工具接口能完成同一计算。该问题同时关联 TD-PLAN-01；SSE 共享 worker 没有改变此判定。状态：**已定位 / 未修复**，见 [验证与诊断](validation/2026-10-02-sse-cleanup.md)。

候选：保留 evidence existence、citation validity、hard policy；重新评估 task-family-specific evidence shape、cross-file minimum、theory-code mandatory pairing。

### 状态

**RE-EVALUATE**

---

# 八、Runtime / Control Plane 相关改进

## TD-RUNTIME-01：当前 Runtime 复杂度高，需要源码级 mastery 后再收敛

当前 Runtime 已承担：Agent iteration budget、tool call budget、tool error budget、duplicate call、deadline、cancel、provider decision、repair metadata、context、evidence accumulation、requirement state、evidence recovery、finalization blocking、trace、activity。

这些功能都不是“没用”，但聚集在一个 bounded loop 中后理解成本很高。

源码学习后再判断是否按职责拆分：Loop State、Execution Policy、Evidence State、Observability、Finalization。

原则：不为了“类更少/更多”重构，只为可理解性、可测试性和边界清晰重构。

2026-10-02 已完成共享文件分类维护切片：允许读取的扩展名、源码扩展名和测试路径识别迁入 `core/tool_agent/project_files.py`，允许读取与源码分类仍是两套独立规则。`code_search` 与 Runtime 复用同一个 `classify_project_evidence_path`，移除工具对 Runtime 的反向依赖及生产分类的重复判断。`code_search.ALLOWED_SUFFIXES` / `classify_project_evidence_path`、`test_discovery.is_test_path` 和旧评测使用的 `runtime._PROJECT_CODE_SUFFIXES` 保留兼容导出；历史评测的独立镜像分类未改。

本切片验证：

- 改动前后对照 3270 个路径，覆盖 Windows/POSIX 分隔符、测试目录、命名约定、扩展名和大小写；分类、可产生的 Runtime evidence、搜索/读取/测试发现输出一致。ToolSpec、产品 Prompt SHA、5/4/2 预算、Runtime 主类及工具 Handler AST、路径安全与读取代码也保持一致。
- 专项回归 **78 passed / 1 skipped**；全量离线回归 **2691 passed / 7 skipped / 4 warnings**。其中一项跳过来自未配置 `GATE4_KNOWLEDGE_CORPUS_ROOT`，随后使用现有语料单独补跑 provenance 检查，**1 passed / 55 deselected**；剩余 6 项跳过均为当前 Windows 无法创建 symlink。
- 本地对照脚本、快照和日志保存在忽略目录 `.tmp_pytest_project_files_20261002/`。未新增长期测试框架，未进行真实模型请求或语义质量评测；预算循环、Planner、Router、Guard、搜索排序和文件访问安全规则保持原行为。

共享分类切片完成；Runtime 整体职责收敛继续开放，不能据此宣布复杂度债或误拒答问题已解决。

### 状态

**AUDIT AFTER MASTERY**

---

## TD-RUNTIME-02：Control State 暴露给 LLM 的字段需要重新评估最小集合

当前 grounded profile 可看到 remaining iterations、remaining tool calls、must terminate、finalization blocked、missing evidence groups、project path counts、available evidence refs、citation requirements。

Control state 越丰富，模型越容易跟随系统，但 Prompt/reasoning burden 也越高，系统内部治理细节暴露更多。

候选：A/B 最小化，只给真正能改变下一步行为的字段。

### 状态

**OPEN / 低到中优先级**

---

# 九、Tool / Registry / Executor 相关

## TD-TOOL-01：Tool 能力以 read-only 为主，缺少真正工程行为

与 `GAP-CAP-01` 联动。

当前 Tool 主要帮助理解 / 定位 / 解释，还不够修改 / 测试 / 修复 / 验证。

### 状态

**HIGH PRIORITY CAPABILITY GAP**

---

## TD-TOOL-02：Tool surface 是否应该进一步“语义化”需要实验

当前 `code_search / read_project_context / find_tests / git_diff` 偏底层。

未来可比较低层 Tool 与更高层 Tool/Skill，如 `inspect_symbol / read_callers / run_target_tests / apply_patch`，但不能一次堆很多 Tool。

原则：一个新 Tool 必须对应真实 capability / reliability delta。

2026-10-02 已实施既有 `read_project_context` 的只读切片：按 Python 函数边界读取，显式截断与范围内分页，类/文档/坏语法回退有限行窗，保留原 5/4/2 预算。R01/R03/R05/N01 在最终配对诊断中获取了旧窗遗漏的关键分支；N01 的非流式读体错误回答得到纠正。整份答案尚有 R05/N02/N03 的语义或引用问题，不能关闭整个债务；见 [验证记录](validation/2026-10-02-source-reading-v2.md)。

2026-10-03 完成 `code_search_v6` 候选实验：Handler 能在现有预算内“宽搜 → scope 收窄 → 读定义”，且默认 matches 与 v5 一致；真实 Agent 在 16 个配对用户请求中却从未使用 scope，两版各 17 次工具调用、相同取证范围，未证明质量提升。**未晋升默认，保留独立候选与完整负结果**；现有 Runtime、Reader、主 Prompt 和 5/4/2 未更改。应先审查路径/对象信息怎样进入下一次模型决策与读取完成判断，再决定是否继续工具 surface 开发；见 [范围搜索验证](validation/2026-10-03-source-search-v6.md)。

### 状态

**PARTIALLY IMPLEMENTED：只读函数获取切片完成；范围搜索候选未晋升；其他高层 Tool / Write Loop 继续待评估**

---

# 十、代码与历史架构清理

## TD-CLEAN-01：Legacy runtime / old product paths 需要归档

v7 已完成一次重要架构整合，把 Context、Planner/Retrieval/Verifier、ToolAgent 收敛进 `UnifiedEngineeringRuntime`。这次 v7 refactor 已完成，不是未来技术债。

但历史旧路径仍可能增加理解成本。源码学习结束后审计：old `agent_runtime`、legacy tool path、unused prompt profiles、frozen historical code、experiment-only path，分类 `KEEP / LEGACY / ARCHIVE / DELETE`。不要边学边删。

### 状态

**PENDING AUDIT**

---

## TD-CLEAN-02：历史 Gate / Repair / Validation 文档过多

项目积累了大量 Gate、Repair、Acceptance、Status、Rollback、Experiment、Roadmap 文档。它们有追溯价值，但不利于理解“当前系统”。

已落实的第一步（2026-10-02）：技术债台账迁入当前文件，由 README 提供入口，工作区旧路径只保留链接。后续只在此处维护债务，避免新增另一份总表。

2026-10-02 审查时，`README.md` 仍把 Streamlit 描述成三种 Demo，并称 Engineering 不是第四种模式；实际 `ui/app.py` 已默认进入 Engineering，旧模式放在 Advanced / Demo。运行手册的“当前基线”也未关联近期回归记录。

同日对齐切片已完成：README 修正 UI 默认入口、会话持久化/API、Agentic history 与 legacy 模式边界，并增加运行手册导航；运行手册同步 CI 清单，按切片分别标注已有全量结果与本次局部验证。当前执行阶段的 cooperative deadline 范围也按源码说明。按项目所有者要求只核对文档与源码，没有测试或模型调用。历史冻结评测结论保持原记录，旧 Runtime 仍有 API/Demo/测试使用；历史文档归档与引用审计继续开放。

后续候选新增：

```text
CURRENT_ARCHITECTURE.md
CURRENT_PRODUCT_PATH.md
EXPERIMENT_INDEX.md
```

旧文档进入 archive / history index。

### 状态

**OPEN / 中低优先级**

---

# 十一、实验 / 开发方法上的过程技术债

## PROCESS-01：Complexity Ratchet

过去容易出现：

```text
一个失败
→ 新增规则 / Router / Guard / Prompt / Gate
→ 原有复杂度不退出
```

新规则：**One Failure, One Hypothesis**。

先明确失败、根因假设、最小 intervention、验证方式，再改。

---

## PROCESS-02：No Capability Delta, No Merge

如果一次 PR 没有用户可见能力增长，也没有可测 reliability 增长，就必须解释为什么值得 merge。

尤其警惕：为框架而框架、为 MCP 而 MCP、为 Graph 而 Graph、为 multi-agent 而 multi-agent、为 vector DB 而 vector DB。

---

## PROCESS-03：Two-Intervention Limit

同一个实验阶段尽量一次最多 1–2 个 intervention，否则结果不可归因。

---

## PROCESS-04：Evaluation 是 Sensor，不是 Product

实验集、benchmark、validator、gate 的作用是发现产品问题，不是让产品越来越像评测系统。

---

## PROCESS-05：新抽象必须退役旧负担

新增 Router、Adapter、Runtime、Prompt Profile、Tool Layer、Protocol 时，都要问：它替代/简化了什么？如果什么都没有退役，复杂度继续累加。

---

# 十二、明确暂缓 / 不做的方向

- **Multi-Agent**：当前不优先引入 Specialist/Critic/Verifier/Arbiter，除非单 Agent + Tool Loop 已证明瓶颈无法解决。
- **GraphRAG**：当前没有证据表明是主瓶颈。
- **Long-term Memory**：先把 bounded conversation context 和真实 engineering loop 做扎实。
- **MCP**：见 TD-MCP-01。
- **为了“现代”而换 Vector DB**：当前已有检索实验，不因为简历关键词强行换。

---

# 十三、已经完成、不要误认为未来技术债的事情

## DONE-01：v7 Unified Runtime 架构整合

已经完成 Context、Planning、Retrieval、Verification、ToolAgent 统一进入一条产品主链。这解决的是 Architecture Integration Drift，不是未来待做的 v9 简化。

## DONE-02：Tool Runtime 的基本安全边界

已经有 Registry、ToolSpec、input schema、output schema、handler isolation、system-generated call_id、duplicate call guard、5/4/2、timeout/cancel、result JSON safety、execution trace。这些不是“都要推倒重写”。

## DONE-03：RAG 基础实验资产

已有 Dense、BM25、Hybrid、RRF、Chunking 对比、Query decomposition、evaluation harness，应作为项目资产保留。

---

# 十四、后续真正的执行顺序

```text
1. 完成当前项目整体回顾
2. 保存并维护本 technical_debt.md
3. ToolAgentRuntime 源码级学习
4. Action / Provider / Prompt / Registry / Executor 源码级学习
5. Unified Runtime 全链路源码级串联
6. 做 Repository Simplification Audit
7. 把候选分为：KEEP / SIMPLIFY / OPTIONALIZE / REPLACE / ARCHIVE / DEFER
8. 做最小 A/B
9. 再开始真正重构
10. 最后补 Edit → Test → Repair vertical loop
```

---

# 十五、优先级总览

| ID | 项目 | 优先级 | 当前状态 |
|---|---|---:|---|
| TD-ARCH-01 | Heavy Control vs Lean Agent | 高 | OPEN |
| TD-AGENT-01 | Custom Action vs Function Calling | 高 | OPEN |
| GAP-CAP-01 | Edit / Patch / Test / Repair Loop | 高 | MISSING |
| TD-PLAN-02 | Front-loaded Retrieval / dynamic knowledge | 中高 | OPEN |
| TD-ROUTER-01 | Router under-activation | 中高 | OPEN |
| TD-ROUTER-02 | Router over-constraint | 中高 | OPEN |
| TD-VERIFY-01 | Structural ≠ Semantic verification | 中高 | OPEN |
| TD-RAG-01 | Chunk / Embedding / 泛化验证 | 中 | OPEN |
| TD-RAG-02 | Dense / Hybrid bounded re-entry | 中 | OPEN |
| TD-PLAN-01 | Planner mandatory 性 | 中 | RE-EVALUATE |
| TD-VERIFY-02 | Finalization Guard 语义负担 | 中 | RE-EVALUATE |
| TD-CI-01 | CI 遗漏近期关键回归 | 近期优先 | CLOSED / 清单已补 / 局部通过 |
| TD-STORE-01 | SQLite 连接关闭与初始化边界 | 近期优先 | PARTIAL / 生命周期已修 / 初始化边界待处理 |
| TD-STORE-02 | 长会话存取缺少容量边界 | 中 | OPEN / 性能未测 |
| TD-RUNTIME-01 | Runtime complexity audit | 中 | PENDING |
| TD-CLEAN-01 | Legacy path archive | 中低 | PENDING |
| TD-CLEAN-02 | 文档 / Gate 历史压缩 | 中低 | OPEN |
| TD-RUNTIME-02 | Control State 最小化 | 中低 | OPEN |
| TD-MCP-01 | MCP 接入 | 当前低 | DEFER |
| TD-ROUTER-03 | Lexical vs LLM Router 正式实验 | 当前低 | DEFER |
| TD-TOOL-02 | 高层语义 Tool / Skill | 读取切片已处理；其他当前低 | PARTIAL / 其他 DEFER |

---

# 十六、后续每个技术债的统一决策模板

```text
问题：
当前实现：
真实失败案例：
证据：
根因假设：

候选改动：
是否增加 abstraction：
是否能退役旧复杂度：

A/B baseline：
核心指标：
成功条件：
失败 / rollback 条件：

最终结论：
KEEP / SIMPLIFY / OPTIONALIZE / REPLACE / ARCHIVE / DEFER
```

避免：

```text
“感觉这里不好”
→ 直接重构
```

而要变成：

```text
“这里在某类任务上产生了可复现 failure”
→ 提出单一假设
→ 做最小实验
→ 用结果决定架构
```

---

# 十七、当前阶段的核心判断

项目过去的问题并不是“做的东西都没用”。真正的问题是：

```text
治理能力增长速度
>
用户可见 Engineering 能力增长速度
```

所以后续方向不是把所有 Guard / Planner / Verifier 全删掉，而是：

```text
保留经过证明的硬约束
+
把语义判断更多交还 Agent
+
让复杂控制层必须证明自己有增量
+
优先补齐真实 Engineering Vertical Loop
```

目标形态：

```text
Strong Model
+
Simple / Bounded Agent Loop
+
Rich but Focused Tools
+
Minimal Hard Guards
+
Evidence Grounding
+
Real Edit/Test/Repair Closure
```

而不是继续变成：

```text
Router
→ Planner
→ Classifier
→ Requirement
→ Verifier
→ Critic
→ More Guard
→ More Gate
```

---

# 近期维护审查（2026-10-02）

本节保留审查事实与候选计划，并记录后续处置。最初审查未修改代码/CI、未运行测试或模型请求；随后授权的维护切片只执行了局部回归。既有 5/4/2 预算保持原样，长会话容量与长期运行性能未测试。

## TD-CI-01：离线 CI 遗漏近期关键回归

- **审查事实：** [CI 工作流](../.github/workflows/ci.yml)显式列出测试文件，审查时未选择 `tests/test_source_definition_reading.py`，因此新增的函数边界、截断、分页与预算专项用例没有被该工作流执行；`test_arch_integration_12a_code_search_kind_filter.py` 与 `test_arch_integration_12a_r1_tool_identity.py` 也未列入。原有 CI 已覆盖部分工具/Runtime/测试发现行为。
- **影响：** 本地全量通过与 CI 对这些能力的保护是两回事；按当前清单，相关能力发生退化时 CI 可能仍然通过。本轮核对的是本地工作流配置。
- **候选：** 将以上 provider-free、无语料下载的关键测试纳入现有离线 job，并同步运行手册的命令；继续排除真实模型实验、模型下载与冻结 Holdout 执行，不直接把所有测试塞进 CI。
- **处置（2026-10-02）：** 上述三个文件与新增 `test_conversation_store_lifecycle.py` 已加入现有离线 job，并同步运行手册。工作流当前选择 33 个文件；本次只运行以上四个文件与既有 `test_product_conversation_20.py`，结果 **70 passed**，无 API key 或真实模型请求。完整 job 与 GitHub Actions 未执行。状态 **CLOSED / 清单遗漏已修复 / 局部通过**，不把本地局部结果写成远程 CI 已通过。

## TD-STORE-01：SQLite 连接关闭与初始化边界

- **审查事实：** [ConversationStore](../api/conversation_store.py)的 CRUD 原来使用 `with self._connect() as conn`，正常路径没有显式 `close()`；唯一显式关闭位于不支持 schema version 的分支。Python 的 SQLite Connection context manager 只管理提交/回滚，不关闭连接，见 [Python 3.14 官方说明](https://docs.python.org/3.14/library/sqlite3.html#how-to-use-the-connection-context-manager)。不能把依赖垃圾回收等同于操作结束时确定释放资源。
- **审查时的另一个边界：** `_connect()` 每次操作都执行建表脚本，而且先执行 DDL 再检查 `PRAGMA user_version`；初始化脚本出错时也缺少显式关闭。后续切片已修复异常关闭，前两项初始化边界仍保留。新增回归验证了不兼容版本的资源释放，没有复现锁错误、资源占用或数据损坏。
- **第一切片：** 只统一连接生命周期，确保成功提交后关闭、失败回滚后关闭、初始化失败时关闭；保留每操作一连接、项目隔离、整轮原子持久化和失败不能发布成功结果的边界。Schema 初始化频率与版本检查顺序作为后续独立切片，避免顺带引入迁移框架。
- **处置（2026-10-02）：** 新增 `_connection()`，由 SQLite context 管提交/回滚，外层 `closing()` 在退出事务后关闭；`_connect()` 初始化异常也显式关闭。所有 CRUD 改用该边界，保留每操作一连接与整轮原子保存。新增 [连接生命周期回归](../tests/test_conversation_store_lifecycle.py) **13 项**，覆盖全部 CRUD、早退、业务异常、第二条消息失败的真实回滚、初始化失败及不兼容版本的资源释放；连同既有会话/API/SSE 与 CI 专项共 **70 passed**。
- **剩余：** 每操作执行 schema 脚本、DDL 早于版本检查的顺序仍保留；后续独立处理。没有长期运行/锁/容量测试。状态 **PARTIAL / 连接生命周期切片完成 / 初始化边界开放**。

## TD-STORE-02：长会话存取缺少容量边界

- **事实：** `load_history()` 每轮查询全部 role/content；[RecentContextWindow](../core/conversation_context/models.py)先将全部消息转换为对象，再取最后 6 条并执行 1200 token 裁剪。token 计算本身只针对候选窗口，问题是前置读取和对象创建仍随历史长度增长。会话列表和详情也没有分页，详情还会解析全部保存的 result。
- **边界：** 已有测试证明模型上下文受 6 条/1200 token 限制；这不能证明数据库 I/O 有同样上界。本轮没有长会话基准，不承诺当前已出现明显卡顿。
- **候选：** 单独设计最近消息读取与 UI 历史分页，存储按已有窗口配置取数据，窗口组件仍唯一决定哪些消息进入 Runtime。不能直接写死 `LIMIT 6`：现有回归要求 `received_count` 保留完整历史数量，并正确报告 `truncated`，消息的时间/rowid 排序也要保持一致。
- **验收：** 长短历史使用相同窗口时选中内容、计数、裁剪标志与旧行为一致；重启/项目隔离不退化，并测量大历史下的读取量和耗时。需先做容量基准与接口设计再估工期，状态 **OPEN / 源码事实确认 / 性能未测**，放在连接修复之后。

---

## 维护约定

后续只要我们讨论到新的明确技术债、重构候选或实验结论，就继续追加到这份文件中。

特别区分：

```text
技术债 ≠ 一定要改
候选重构 ≠ 已经决定重构
实验失败 ≠ 应该继续加控制层
```

所有真正的架构决策尽量以：

```text
源码事实 + 失败案例 + 对照实验
```

为依据。
