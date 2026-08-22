# G11-01：统一 Engineering Agent 与异构 Evidence 架构

## 结论

项目的产品定位是 **Evidence-Grounded AI Engineering Agent**。普通用户不应直接面对 Basic RAG、Agentic RAG、Structured Tool Agent 三个实现入口，因为它们是不同阶段、不同职责的 baseline/debug/regression interface。产品层新增统一的：

```text
POST /engineering/query
```

旧的 `/query`、`/agent/query`、`/tool-agent/query` 保留，不删除、不重写，继续作为历史兼容、调试和回归接口。

## 为什么统一入口选择 Tool Agent

Gate 3 Agentic RAG 仍然有价值：它擅长 Planner → Decomposition → Adaptive Retrieval → Verifier 的复杂知识检索，并且已经有正式 benchmark 与冻结基线。

当前 Tool Agent 的职责不同：Decision → Tool → Observation → Decision。它已经可以访问 Knowledge、Repository、Git Change 和 Test Discovery 四类后端，所以 G11-01 的统一 Engineering Agent v1 选择现有 `ToolAgentRuntime` 作为 control plane。以后如果 Engineering Benchmark 证明复杂知识问题需要更强的 Agentic Retrieval capability，再考虑暴露它；本次不把两个 controller 嵌套。

## 不复制 Agent Loop

新增的 `EngineeringAgentFacade` 只是产品入口适配器，内部直接委托现有 `ToolAgentRuntime.run()`。它不实现 Planner、Router、Executor、Verifier，也不引入第二套预算或决策状态机。这样产品入口和运行时演进可以解耦，同时避免 Gate 4 的安全边界出现两份实现。

## Observation 与 Evidence

Observation 是一次 Tool 执行后反馈给模型的事实快照，可能包含错误状态和不可信内容；它服务于下一次 Decision，不是最终 API 的展示合同。

Evidence 是从成功 Observation 中抽取的、有边界的公开事实：

| 来源 | Evidence kind | 公共字段 |
|---|---|---|
| `knowledge_search` | `knowledge` | `source_name`, `chunk_id`, `score`, `rank`, `snippet` |
| `read_project_context` | `project_code` / `project_doc` / `project_test` | `path`, `start_line`, `end_line`, `snippet` |
| `git_diff` | `project_change` | `path`, `start_line`, `end_line`, `snippet` |

Knowledge Evidence 的 snippet 最多 500 字符；source identity 必须是安全相对身份，不能是本机绝对路径。Project Evidence 继续使用现有 repo-relative path 和最多 2000 字符上下文。只有 `observation.status == "ok"` 且 match 通过强类型校验时，Knowledge Evidence 才会进入最终响应。Tool error、malformed match 和不安全 provenance 都不会生成 Evidence。

## 统一 Evidence Contract

`/engineering/query` 使用一个统一的 Evidence 列表，并按实际产生顺序使用全局 ID：`E1`、`E2`、`E3`。Knowledge 命中两个片段后再读一个源码窗口时，顺序就是 `E1 knowledge`、`E2 knowledge`、`E3 project_code`，不区分 `K1`、`P1` 两套编号。

Knowledge Evidence 按 `source_name + chunk_id` 去重；chunk 缺失时按 `source_name + snippet` 去重。Project Evidence 仍按 `kind + path + start_line + end_line` 去重。这里没有引入复杂的 Content Addressing 或新的 evidence backend。

统一响应只包含当前真实存在的字段：status、answer、reason/failure code、bounded runtime counters、安全 trace 和 evidence。没有 planner、route、critic、memory、checkpoint 等伪造层。

## Trace、Evidence 与 CoT

Trace 说明系统做了什么，只保留事件类型、iteration、action/tool、call/status、错误码和计数。Evidence 说明工具实际读到了什么。模型 Prompt、CoT、raw observation、provider response、完整 diff/code 正文和 traceback 不进入 Trace。正常的 Knowledge snippet 可以作为 Evidence 返回，因为它就是用户请求的知识事实，但不应被混入 Trace。

## 安全和兼容边界

`knowledge_search` 继续复用现有 RetrievalPort，不重新检索。Handler 在成功 Observation 前拒绝 POSIX、Windows drive、UNC 等绝对 provenance；Runtime 再以 `KnowledgeEvidence` 强类型边界 fail closed。统一入口只接受 `{ "question": "..." }`，额外字段全部拒绝，不开放 provider、model、budget、tool allowlist、system prompt、repo root 或 history。

旧 `/tool-agent/query` 的响应 schema 保持 `tool_agent_query_response_v1`。内部 Runtime 可以保存异构 Evidence，但旧 endpoint 继续输出历史 project evidence 形状；新 `/engineering/query` 才输出统一 Knowledge/Repository/Change/Test contract。这样新产品能力不会破坏旧 benchmark、debug 和 regression 客户端。

## 为什么这次不加 Router 和 Context

现在已有的 ToolSpec 动态进入 Tool Agent，knowledge 与当前工程的边界已在 Prompt v3 和 Tool description 中明确，因此不需要新 Router。G8 已证明 conversation context 有价值，但 Tool Agent 尚未接入正式 context 语义；为了避免同时改变两套状态边界，G11-01 暂不接 History/Memory。

预算仍冻结为 `5 iterations / 4 tool calls / 2 tool errors`。Knowledge-only 只需一次 Tool call；Cross-source 的典型路径为 knowledge_search → code_search → read_project_context → final，使用 3 次 Tool call；Change/Test 路径为 changed_files → git_diff → find_tests → read_project_context → final，使用 4 次 Tool call。

## 后续演进与面试表达

统一入口使 Theory ↔ Code、Change Impact、测试关联和知识解释共享一个 API Evidence Plane。后续可以在这个边界上加入更丰富的 Context 或专门的 Retrieval capability，但应继续保持控制平面、Evidence backend 和产品 contract 的职责分离。

面试中可以这样解释：项目没有把所有检索都伪装成一种 RAG。Knowledge RAG 是持久共享技术知识库；Repository 是按需读取的工程事实；Git Change 和 Test Discovery 是变化与验证事实。Tool Agent 负责有限、可审计的动作编排，Runtime 只把成功工具结果提炼成安全、去重、可引用的异构 Evidence，统一入口负责把这些事实交给用户。

## 本次验证

- Knowledge-only：`knowledge_search → final` 返回 `knowledge` Evidence。
- Repository-only：`code_search → read_project_context → final` 返回 `project_code` Evidence。
- Cross-source：同一次 run 同时返回 `knowledge` 与 `project_code`，并使用全局 E ID。
- Change/Test：`changed_files → git_diff → find_tests → read_project_context → final` 仍在 5 iterations / 4 tool calls 内返回 `project_change` 与 `project_test`。
- 未修改 Tool Prompt、ToolAgentBudget、Runtime loop、Agentic RAG、Context、UI 或 benchmark。
