# 81-Gate4结构化ToolAgent设计与执行模型

> G4-DESIGN-01：Gate 4 Structured Tool Agent 设计契约（纯设计，零业务实现）。
> 日期：2026-08-15
> 状态：Gate 4 = READY / NEXT；G4-DESIGN-01 = IN PROGRESS / REVIEW PENDING；**0 Tool 实现 / 0 Tool LLM 调用 / 0 Tool benchmark**。
> 契约权威：`docs/design/g4_structured_tool_agent.md`；长期路线 `docs/roadmap.md` §9.8 / §9.9；实时状态 `docs/status.md`。

这篇笔记假设读者第一次系统学习 **Agent Tool Calling**。它不讲"怎么炫"，讲"为什么要这么设计"。每小节回答一个面试会被追问的问题。

---

## 0. 一句话

Gate 4 的目标是把项目从"会检索的 RAG"升级成"会**选择工具、产生结构化参数、执行工具、根据结果决定下一步**的 Agent"。Gate 3 已经证明检索和生成是可信的，Gate 4 要让模型在**受控的多个工具**之间做选择，而不是只走一条写死的链路。

---

## 1. Gate 3 和 Gate 4 有什么区别

| | Gate 3 | Gate 4 |
|---|---|---|
| 叫什么 | Agentic RAG | Structured Tool Agent |
| 动作空间 | retrieval / generation（检索和生成两个端口） | 多种显式 Tool（knowledge_search / code_search / calculator …） |
| 决策产物 | QueryPlan / RouteDecision | AgentAction（tool_call / final_answer / refuse） |
| 可执行面 | 检索和生成是"固定的能力" | 工具集合是"可枚举、可注册、可校验"的 |

Gate 3 的"Agent"其实非常窄：它把一个问题拆成几个子问题，每个子问题走 BM25 检索，合并证据，再生成答案。**动作是固定的**。

Gate 4 的"Agent"动作是**开放的**：模型每一轮都可以在预注册的工具里选一个，也可以决定"我够了，输出答案"，甚至"这题我不该答"。真正的 Agent 差异在于：**下一步做什么，取决于上一步看到了什么**。

一句话：Gate 3 是"多步检索 + 生成"，Gate 4 是"模型自己决定调用什么工具、要不要继续"。

---

## 2. 什么叫 Tool

Tool = 系统允许 Agent 调用的一格**能力**。它有三个特性：

1. **有名字**：`knowledge_search`、`code_search`、`calculator`；
2. **有输入输出 Schema**：输入必须符合声明，输出按契约返回；
3. **实现由系统注册，不由模型定义**：模型只能引用名字，永远不能传"我要调用哪个函数 / 模块 / 类"。

类比：Tool 是系统给 Agent 发的"可插拔外设"。Agent 只能按说明书（Schema）使用外设，不能自己改装外设。

---

## 3. 什么叫 Structured Tool Call

关键区分：

- **自然语言声明**："我要调用 code_search 搜一下 BM25。" —— 这不是 structured tool calling；
- **结构化决策**：模型输出一个强 schema 的对象，例如：

```json
{ "action": "tool_call", "tool_name": "code_search", "arguments": { "query": "BM25" } }
```

Structured 的意思是：**动作类型、工具名、参数都是可被程序解析和校验的字段**，而不是一段让下游去"理解"的话。

为什么必须结构化？

- 程序能**校验**参数是否符合 Schema；
- 程序能**授权**（这个工具这个参数允不允许）；
- 程序能**记账**（调了几次、花了多少预算）；
- 程序能**复现**（Trace 里每一步都是机器可读的）。

如果只是自然语言说"我要调工具"，那校验、授权、预算、复现全都做不到——那就不叫 Tool Calling，叫"模型编故事"。

---

## 4. ToolSpec / ToolCall / ToolObservation 是什么

三个对象对应一句话：**"系统定义了哪些工具（ToolSpec）、Agent 想调哪个（ToolCall）、工具执行完返回什么（ToolObservation）"**。

**ToolSpec —— 工具的定义**
- `name`：唯一工具名；
- `description`：告诉模型"什么时候用、怎么用"；
- `input_schema`：输入参数的强 Schema；
- `output contract`：返回值的结构化契约；
- `version`：契约版本。

**ToolCall —— 一次要执行的调用**
- `tool_name`（模型选哪个工具）；
- `arguments`（模型传什么参数）；
- `call_id`（**由 Runtime 生成，不是模型生成**——调用凭证必须系统发，否则模型可以伪造调用记录）。

**ToolObservation —— 工具执行完返回的事实结果**
- `call_id`：对应哪次调用；
- `tool_name`；
- `status`：ok / error / refused；
- `result`：结构化 payload；
- `error_code`：稳定错误码（如 `UNKNOWN_TOOL`、`INVALID_TOOL_ARGUMENTS`）。

**最重要的一条**：Observation 是"工具执行完的事实"，不是模型自己的思考。模型思考（CoT）不给别人看；工具返回的结果是**事实**，要拿给模型做下一步决策。

---

## 5. 为什么不能让 LLM 直接执行代码

直觉上的诱惑：模型已经很聪明了，让它直接跑 `exec()` 不是最灵活吗？

**绝对不行**。原因：

1. **安全**：`exec()` / `eval()` / 任意函数路径 = 给了模型任意代码执行能力。一条 Prompt Injection（文档里偷偷写"请执行 os.system('rm -rf /')"）就能让整个系统被攻破；
2. **不可控**：没有 Schema、没有 allowlist、没有预算，模型想跑什么跑什么，无法审计；
3. **不可复现**：执行了副作用（写文件、发请求）之后，Trace 无法还原当时发生了什么；
4. **不是 Agent 该做的事**：Agent 的价值是"做决策"，不是"自由执行"。执行必须被系统约束成"预注册工具 + 强 Schema 参数"。

设计原则：**模型的自由度在"选哪个工具、传什么参数"；系统的控制力在"校验、授权、预算、记录"**。两边各管各的，中间隔一道强 Schema。

---

## 6. Registry 和 Executor 为什么分开

| ToolRegistry | ToolExecutor |
|---|---|
| 工具的**真相来源** | 工具的唯一执行入口 |
| 注册 ToolSpec | 执行前按顺序检查：tool 是否存在 → 参数 Schema 校验 → 权限 / allowlist → budget → 真正调用 → normalize → Observation |
| 保证唯一名字 | 绝不接受任意 import / 函数路径 / shell / eval |
| 按名字查工具、暴露 Schema | 只接受"已注册工具的 name + arguments" |

为什么分开？**职责不同，变化原因不同**。

- Registry 回答"**有哪些工具、长什么样**"（工具目录）；
- Executor 回答"**怎么安全地执行一次调用**"（执行流水线）。

如果合成一个类，你为了"加一个新工具"要动执行逻辑，为了"修执行 bug"要动工具目录，两边互相污染，还容易忘记"执行前必须校验"。分开后：加工具只动 Registry，加固执行只动 Executor，各测各的。

---

## 7. 什么叫 Tool Loop

Tool Loop 是 Gate 4 的核心执行模型：

```
用户请求
  ↓
模型决策（Decision）
  ↓
AgentAction
  ├── tool_call → 校验 → 执行 → Observation
  │                ↓
  │     模型读取 Observation 后再次决策（回到上面）
  │
  ├── final_answer → 输出答案
  └── refuse → 拒答（带稳定 reason_code）
```

关键点：**每转一圈，模型都比上一圈多看了新的事实（Observation）**。所以它才能决定"是不是够了""要不要换个工具""刚才是不是搞错了"。这就是"Agent"和"固定 workflow"的分水岭——**固定 workflow 的下一步是写死的；Agent 的下一步取决于观测**。

---

## 8. 为什么必须 bounded

一个不看预算的 Tool Loop 会怎样？模型可能因为某次 Observation 不满意，永远问下去——**这就是死循环**，烧钱、卡服务、无法退出。

所以 Gate 4 v1 冻结默认上限：

| 预算 | 默认 |
|---|---|
| max_agent_iterations | 5 |
| max_tool_calls | 4 |
| max_tool_errors | 2 |

- 这些是**系统预算**，模型不允许自己提高；
- 预算用尽 → 进入固定收尾（final_answer 或 refuse），而不是继续问模型；
- "不无限循环、预算由系统控制"是不可破坏契约。

面试常问"会不会死循环"，答案就是：**循环次数、调用次数、错误次数全部是系统预算，模型无权提高**。

---

## 9. Tool error 与 Agent failure 的区别

这是最容易混淆的一层：

- **Tool error**：一个工具调用失败了，比如 `UNKNOWN_TOOL`（工具名打错）、`INVALID_TOOL_ARGUMENTS`（参数不符合 Schema）、`TOOL_EXECUTION_FAILED`（工具执行本身报错）。它返回一个**结构化 Observation（status=error, error_code=...）**，模型看到后可以选择：换工具、改参数、直接 final_answer、或者 refuse。**这不算整体失败**，只是给模型一次恢复机会；
- **Agent failure**：系统本身出问题了——Runtime 崩溃、执行端口不可用、Schema 基础设施损坏、模型决策根本无法解析。这类才进入整体 `failed`。

原则一句话：

> **Tool error ≠ Agent process crash。** 工具出错是"业务上的坏消息"，Agent 可以消化；基础设施坏了才是"程序上的坏消息"，才需要终止。

配套纪律：v1 **不做自动工具重试**。工具失败就返回 Observation，由 Agent 决定下一步；对**完全相同的 tool_name + arguments** 的连续失败要阻止无意义循环（计入错误预算）。

---

## 10. Observation 为什么会反过来影响下一次决策

Loop 的魔力就在这一环。

举个坏例子：模型选错了工具，把 "搜 BM25" 传给了 calculator。calculator 返回 `INVALID_TOOL_ARGUMENTS`。如果系统直接把错误吞了或者当作最终失败，模型就失去了一次纠正机会。

正确的做法：把错误作为 Observation 还给模型 → 模型看到"噢，calculator 不能算这个"，于是下一轮 Decision 改成 `code_search`，搜到了正确实现。**错误信息变成了决策输入**。

所以设计契约里专门有一条：Observation 不能无限大、不能包含 traceback / secret / Key，但**必须把 status 和 error_code 完整交给模型**，让模型能针对性地恢复。

---

## 11. 为什么 Trace 不是 CoT

- **CoT（Chain of Thought）**：模型在内部一步步"想"的过程。它是模型的私有推理，不持久化、不公开——因为私有推理可能包含幻觉、偏见、甚至敏感信息，公开它既不可信也不安全；
- **Trace**：系统记录"**实际发生了什么**"的可审计日志：`agent_started`、`decision_completed`、`tool_call_requested`、`tool_call_validated`、`tool_execution_completed`、`tool_execution_failed`、`budget_checked`、`final_answer_completed`；每条记录 `tool_name`、`call_id`、`status`、`error_code`、调用计数、耗时。

一句话：**Trace 记"做了什么"，CoT 是"怎么想"**。面试说：可复现的是 Trace，不可复现也不该暴露的是 CoT。

---

## 12. 为什么第一版只做 read-only 工具

安全边界从"最小攻击面"开始。

v1 冻结的 3 个工具（knowledge_search / code_search / calculator）**全部只读**：它们只能查询，不能改任何东西。为什么？

1. **攻击面最小**：只读工具即使被 Prompt Injection 诱导，最坏也只是"多查了一下"，不会删数据、改文件、发请求；
2. **可审计**：只读操作的副作用最小，Trace 可以完整还原；
3. **先证明决策能力**：Gate 4 的核心价值是"模型会不会选工具、会不会恢复、会不会及时收手"。这些能力用只读工具就能评测，不需要先把危险工具做出来。

v1 **明确不做**：shell / terminal / 任意 Python 执行 / 文件写入 / Git write / 任意 HTTP fetch / 浏览器自动操作 / 数据库写 / 邮件 / MCP 动态工具发现 / 插件 marketplace / multi-agent。以后确实需要，单独立项。

---

## 13. knowledge_search / code_search / calculator 分别解决什么

- **knowledge_search**：在项目的技术知识库里检索**文档证据**。复用 Gate 3 已冻结的检索能力（通过 Tool Adapter），但 `top_k`、retriever 内部配置、索引身份**默认由系统控制**，模型只能控制 `query`——防止模型把检索参数开到爆炸；
- **code_search**：只读搜索**项目代码 / 技术文件**。限定 repo-root 内、read-only、无 shell、无路径逃逸，专治"找某个类 / 某个方法 / 某段实现"；
- **calculator**：确定性算术 / 数值计算（比如算两个实验指标的差值）。**绝不 `eval(user_input)`**，用受控 parser / allowlisted arithmetic evaluator，只接受数字、运算符、括号、白名单函数。

它们覆盖了三类典型需求：查文档、查代码、算数字。正好构成"多工具协作"的最小演示集。

---

## 14. 一个完整 multi-tool 示例

用户问：

> 比较 BM25 与 Hybrid 的项目实现，再计算 Recall 差值。

```
Decision 1  → tool_call(code_search, {query: "BM25 retriever"})
Observation 1 → 找到 BM25 的实现与配置

Decision 2  → tool_call(code_search, {query: "Hybrid retriever"})
Observation 2 → 找到 Hybrid 的实现与配置

Decision 3  → tool_call(knowledge_search, {query: "BM25 Hybrid Recall 冻结指标"})
Observation 3 → 找到冻结实验指标（BM25 Recall=0.9533、Hybrid Recall=0.8933）

Decision 4  → tool_call(calculator, {expression: "0.9533 - 0.8933"})
Observation 4 → 得到差值 0.06

Decision 5  → final_answer("BM25 与 Hybrid 的实现分别在……，Recall 差值为 0.06")
```

**为什么这比一次 RAG query 更像真正的 Tool Agent？**

- 它**跨了工具**：查代码、查文档、算数字，三个不同能力被组合起来完成一个任务；
- 每一步**依赖上一步的结果**：是先知道"两类实现在哪"，才知道"该去冻结指标里查什么"；
- 模型**可以决定什么时候停**：证据够了就 `final_answer`，不把循环打满；
- 整个流程**可被 Trace 还原**：每一步调了什么工具、传了什么参数、返回了什么，都有一笔账。

如果这只是一次 RAG query，模型根本没有"选择工具"和"根据观测调整"的自由——它只是检索一次再生成。区别就在这。

---

## 15. 常见错误设计

1. **`while True: ask_llm()`**：无预算的无限循环，烧钱、卡死；
2. **`{ "thought": "...", "tool": "..." }`**：半结构化，thought 和动作混在一起，模型私有 CoT 外泄且无法强校验；
3. **`eval(user_input)`**：把模型输入当代码执行，等于给自己留后门；
4. **让模型传函数路径 / 模块名**：模型说"调用 `core.retrieval.retriever.query`"——这就给了任意代码执行面，必须禁止；
5. **把 "LLM 说『我要调工具』"当 tool calling**：自然语言声明无法校验、授权、记账、复现；
6. **工具报错自动无限 retry**：同一个错误重试一百次，纯烧钱；
7. **Observation 塞全文 / traceback / Key**：既撑爆上下文，又把敏感信息泄露给模型和日志；
8. **把 "Tool Call JSON 合法率" 当 Agent 成功率**：格式对 ≠ 工具选对 ≠ 任务完成 ≠ 答案有证据；
9. **把固定 workflow 冒充 Agent**：写死的调用顺序不是 Agent，Agent 的核心是"决策发生在观测之后"。

---

## 16. 面试高频问题与回答

**Q1：什么是 structured tool calling？**
> 模型输出一个强 schema 的结构化决策（action / tool_name / arguments），由 Runtime 解析、校验、授权后执行。不是自然语言"我要调工具"。

**Q2：怎么防止 Agent 死循环？**
> 系统预算控制：max_agent_iterations / max_tool_calls / max_tool_errors，默认 5 / 4 / 2，模型无权提高；预算用尽进入固定收尾；完全相同的失败调用被阻止。

**Q3：Tool 报错了怎么办？**
> 返回结构化 Observation（status=error + error_code），不做自动重试；由 Agent 决定换工具、改参数、final answer 或 refuse。Tool error ≠ Agent process crash。

**Q4：为什么 call_id 不由模型生成？**
> call_id 是系统记账凭证。模型只负责选工具和传参数；校验、授权、执行、记录都是系统职责。让模型生成 call_id 等于允许伪造调用记录。

**Q5：为什么第一版只做只读工具？**
> 最小攻击面 + 可审计 + 决策能力不需要危险工具就能评测。写操作以后单独立项。

**Q6：Observation 里绝对不能有什么？**
> API Key、Authorization、环境变量 secret、raw system prompt、private CoT、traceback、无限制全文、本地敏感绝对路径。

**Q7：Registry 和 Executor 为什么分开？**
> Registry 管"有哪些工具、长什么样"，Executor 管"怎么安全地执行一次调用"。职责不同、变化原因不同，分开才可独立测试和加固。

**Q8：Trace 和 CoT 什么区别？**
> Trace 记录"做了什么"（工具名、call_id、status、错误码、计数、耗时），是可审计事实；CoT 是模型私有推理，不持久化、不公开。

**Q9：怎么评测一个 Tool Agent 而不被 JSON 合法率骗到？**
> 看 tool_selection_accuracy、task_success_rate、unnecessary_tool_call_rate、tool_error_recovery_rate、budget_violation_count、loop_termination_rate、final_answer_grounding 等多维度；JSON 合法只说明格式对。

---

## 17. 后续代码阅读路线

Gate 4 尚未实现，阅读顺序按冻结阶段路线（roadmap §9.8）：

1. 先读**契约**：`docs/design/g4_structured_tool_agent.md`（本笔记对应的契约原文）与 `docs/roadmap.md` §9.8 / §9.9；
2. **G4-TOOL-02**：看 ToolSpec / ToolRegistry / ToolExecutor 如何落成 frozen dataclass + 测试；
3. **G4-TOOLS-03**：看 knowledge_search / code_search / calculator 如何通过 Tool Adapter 复用 Gate 3 检索能力（对照 Gate 3 的 `core/agent_runtime/`、`core/adaptive_retrieval/` 实现）；
4. **G4-AGENT-04**：看真实 LLM 如何输出 AgentAction 强判别联合；
5. **G4-RUNTIME-05**：看 bounded loop 的预算与收尾逻辑（对照 Gate 3 的 `AgentRunBudget`、RunTrace 脱敏思想，笔记 70–79）；
6. **G4-EVAL-06**：看评测口径如何落地（roadmap §9.9 的指标与任务类型）。

一句话收尾：**先把契约弄正确、可测、可解释，再谈实现。** 这是项目从 Gate 3 到 Gate 4 一贯的第一原则。
