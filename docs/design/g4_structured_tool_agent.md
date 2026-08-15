# Gate 4：Structured Tool Agent 设计契约

> 任务：G4-DESIGN-01（设计契约，零业务实现）
> 日期：2026-08-15
> 基线提交：`c2cf0d724d5ade31a4bac9b504c6897480d3df95`（docs: close Gate 3 after final holdout seal）
> 状态：Gate 4 = READY / NEXT；G4-DESIGN-01 = IN PROGRESS / REVIEW PENDING；**0 Tool 实现 / 0 Tool LLM 调用 / 0 Tool benchmark**
> 权威来源分层：本设计文档记录 Gate 4 架构边界、核心数据契约、执行模型、安全边界、阶段路线与评测口径；实时状态以 `docs/status.md` 为准；长期路线以 `docs/roadmap.md` 为准；Gate 3 冻结成绩以 `docs/experiments/gate3_holdout_final.json` 为准，**不得重新解释**。

本设计只回答 Gate 4 的**架构契约**，不描述任何已实现功能。文中所有"必须 / 禁止 / 上限"都是契约要求，不是现状描述。

---

## 1. 总目标

把 Gate 3 的 RAG-specific Agent Runtime 扩展为受控的 **Structured Tool Agent**：

> 模型在**预注册工具集合**中选择工具，产生**结构化参数**，执行工具，读取 **Observation**，并在严格预算和安全边界内决定继续调用工具还是输出最终答案。

必须明确区分：

| | Gate 3 | Gate 4 |
|---|---|---|
| 形态 | Agentic RAG | Structured Tool Agent |
| 主要动作空间 | retrieval / generation | 多种显式 Tool |
| 决策产物 | QueryPlan / RouteDecision | AgentAction（tool_call / final_answer / refuse） |
| 可执行面 | 检索与生成端口 | 预注册 Tool（通过 ToolRegistry 暴露） |

两条硬性禁止：

- **禁止把固定 workflow 冒充 Agent**：一次写死的调用顺序不是 Agent，Agent 的核心是"每次决策都发生在观测之后"；
- **禁止把"LLM 输出一句『我要调用某工具』"称为 structured tool calling**：structured tool calling 必须是一个强 schema 的结构化决策，由 Runtime 解析、校验、授权后执行，而不是一段自然语言声明。

---

## 2. 基线前提（Gate 3 = CLOSED / FROZEN）

- `gate3_system_freeze_id = 2ec11a69b173`
- `gate3_dataset_freeze_id = 257fa0d0a6d6`
- `formal_holdout_run_id = cb157fd3837f`

约束：

- Gate 4 **不读取**任何 Gate 3 sealed Holdout；
- Gate 4 **不修改**任何 Gate 3 freeze / artifact；
- Gate 4 **不重跑** Gate 3 冻结 RAG 来验证或改进冻结成绩；
- Gate 3 的冻结结论是本任务的既定事实，不作为 Gate 4 可调参数。

---

## 3. 架构边界：Gate 3 冻结实现不被 Gate 4 反向改写

```
Gate 3 frozen runtime
        │
        │ 作为能力复用（Tool Adapter）
        ▼
Gate 4 Tool Adapter
        │
        ▼
Structured Tool Agent（新的 Tool Runtime 契约）
```

- Gate 3 frozen runtime（`/agent/query`、`core/agent_runtime/`、`core/adaptive_retrieval/` 等）**保持不变**；
- Gate 4 通过 **Tool Adapter** 复用 Gate 3 的能力（例如 knowledge_search 复用检索与证据能力），而不是直接改写 Gate 3 runtime；
- 未来独立 namespace：**`core/tool_agent/`**（本任务只是设计，不创建目录）；
- 后续优先新增独立入口 **`/tool-agent/query`**，而不是改变已经冻结的 `/agent/query` 行为。

即：Gate 3 冻结实现是"被复用的能力来源"，Gate 4 是"新的动作空间层"。任何为 Gate 4 需要的改动都必须落在新的 Tool 层，不回写冻结层。

---

## 4. 核心数据契约

### 4.1 ToolSpec —— 系统允许调用的一个工具

代表"系统允许 Agent 调用的一个工具"，是工具事实的定义单位。至少包含概念字段：

| 字段 | 职责 |
|---|---|
| name | 唯一工具名 |
| description | 告诉模型"这个工具什么时候用、做什么、怎么用" |
| input_schema | 输入参数的强 Schema（JSON Schema 或等价） |
| output contract | 返回值的结构化契约（字段、类型、上限） |
| version | 工具契约版本 |

不可破坏契约：

- **tool name 唯一**；注册时重复即失败；
- **Registry 是工具的真相来源**：Agent 只能调用 Registry 里已注册的 Tool；
- **模型不能动态创建工具**：不存在"让模型注册新工具"的路径；
- **模型不能指定 Python module / class / function**：模型只能引用 `tool_name`，永远不能传"实现路径"；
- **input 必须强 schema**：参数必须通过 Schema 校验；
- **unknown argument 默认拒绝**：Schema 之外的参数一律拒绝，不做宽容合并。

### 4.2 ToolCall —— 一次准备执行的工具调用

```
ToolCall
  call_id      ← 由 Runtime 生成，不由 LLM 生成
  tool_name    ← 由 LLM 选择
  arguments    ← 由 LLM 提供（受 Schema 约束）
```

关键决定：

- **call_id 由 Runtime 生成，不由 LLM 自己生成**。模型只负责两件事：选哪个工具、传什么参数；
- 系统负责：生成 call_id、校验、授权、执行、记录；
- 一份 ToolCall 在通过校验前**不算数**，不进入执行。

### 4.3 ToolObservation —— 工具执行后的事实结果

至少表达：

```
ToolObservation
  call_id
  tool_name
  status            ← ok / error / refused
  result            ← 结构化 payload（按 output contract）
  error_code        ← 稳定错误码（见 §9）
```

- Observation 是 **Tool 执行后返回给 Agent 的事实结果**；
- Observation **不是 CoT**：不包含模型的隐藏推理；
- 不得把异常 traceback、secret、Authorization、API key 等直接塞给模型或 Trace；
- 失败时仍返回结构化 Observation（带 error_code），让 Agent 有机会恢复，而不是中断整个请求（见 §9）。

### 4.4 AgentAction —— Agent 每一步决策的强判别联合

Gate 4 v1 至少定义三种动作，建议强 discriminated union：

```
AgentAction
├── ToolCallAction      → tool_call
├── FinalAnswerAction   → final_answer
└── RefuseAction        → refuse
```

约束：

- `tool_call`：**必须有** `tool_name` + `arguments`，**不能同时**携带 final answer；
- `final_answer`：**不得**携带任何 tool 字段；
- `refuse`：**必须有**稳定的 `reason_code`（枚举，不是自由文本）。

**不要**设计成 `{ "thought": "...", "tool": "..." }` 这种半结构化形态。模型私有 CoT 不持久化、不公开；公开的只有结构化动作与可审计摘要。

---

## 5. ToolRegistry / ToolExecutor 两层边界

必须设计两层，**不能混成一个大类**。

### 5.1 ToolRegistry —— 工具的真相来源

职责：

- 注册 ToolSpec；
- 保证唯一名称；
- 按名称查找 Tool；
- 暴露全部工具 Schema（供 Prompt / 校验 / 能力枚举使用）；
- 能力枚举（告诉系统"现在有哪些工具可用"）。

Registry **不执行工具**。

### 5.2 ToolExecutor —— 工具的唯一执行入口

执行前按固定顺序检查：

```
tool 是否存在（查 Registry）
    ↓
arguments schema validation（按 ToolSpec.input_schema）
    ↓
权限 / allowlist
    ↓
budget（步数 / 调用数 / 错误数）
    ↓
真正调用
    ↓
normalize result（按 ToolSpec.output contract）
    ↓
ToolObservation
```

**执行器绝不能接受**：

- 任意 Python import；
- 任意函数路径（模型不能传"我要调用哪个函数/模块/类"）；
- 任意 shell command；
- 任意 `eval()` / `exec()`。

工具的"实现"只由系统在注册 ToolSpec 时决定，Agent 永远只能传 `tool_name + arguments`。

---

## 6. Gate 4 v1 首批工具范围

设计阶段先冻结 **3 个 read-only 工具类型**。

### Tool A：knowledge_search

- 定位：在项目技术知识库中检索证据；
- 复用现有 RAG / Retrieval 能力（通过 Tool Adapter）；
- **不要让模型控制底层危险参数**：
  - `query` = model controlled；
  - `top_k` / retriever internal config / index identity = **默认由系统配置控制**，不允许模型任意扩大；
- **Gate 4 不重跑 Gate 3 的 frozen RAG**：knowledge_search 是新的 Tool 入口，复用的是检索能力契约，不是重新执行冻结实验。

### Tool B：code_search

- 定位：只读搜索当前项目中的代码 / 技术文件；
- v1 必须限定：
  - **repo-root 内**；
  - **read-only**；
  - **无文件修改**；
  - **无 shell**；
  - **无路径逃逸**（参数必须约束在项目根目录内，`..` / 绝对路径 / 通配符逃逸一律拒绝）。

### Tool C：calculator

- 定位：确定性算术 / 数值计算；
- 明确写：**不得 `eval(user_input)`**；
- 未来实现使用受控 parser / allowlisted arithmetic evaluator（只接受数字、运算符、括号、白名单函数，返回确定结果或 INVALID_TOOL_ARGUMENTS）。

### Gate 4 v1 明确不做

- shell tool；
- terminal tool；
- arbitrary Python execution；
- 文件写入工具；
- Git write tool；
- 任意 HTTP fetch；
- 浏览器自动操作；
- 数据库写操作；
- 邮件发送；
- MCP 动态工具发现；
- 第三方 plugin marketplace；
- multi-agent。

以上以后确实需要时**单独立项**，不混入 v1。

---

## 7. Bounded Tool Loop

整体流程：

```
User Request
      ↓
LLM Decision
      ↓
AgentAction
   ↙              ↘
tool_call        final_answer / refuse
   ↓
validate（Schema / 权限 / budget）
   ↓
ToolExecutor
   ↓
ToolObservation
   ↓
LLM Decision（读取 Observation 后再次决策）
   ↓
...
```

**绝对不能**：

```
while True:
    ask_llm()
```

Gate 4 v1 建议冻结默认上限：

| 预算 | 默认值 |
|---|---:|
| max_agent_iterations | 5 |
| max_tool_calls | 4 |
| max_tool_errors | 2 |

- 这些是**系统预算**，LLM 不允许自己提高；
- 具体代码实现时如果发现字段命名更合理，可以保留语义不变地微调；
- **"不无限循环、预算由系统控制"是不可破坏契约**。

---

## 8. 重复调用与 retry

Gate 4 v1：

- **不做自动工具重试**；
- Tool 失败以后返回 `ToolObservation(status=error, error_code=...)`；
- 由 **Agent** 决定下一步：换工具 / 改参数 / final answer / refuse；
- 对**完全相同的 tool_name + arguments** 的连续失败调用，设计应明确阻止无意义循环（计入 max_tool_errors 预算；触发后进入固定拒绝路径）。

**不要**设计成：

```
工具报错 → Runtime 自动无限 retry
```

---

## 9. 错误模型

必须区分以下错误类别（枚举名可微调，语义不能缺失）：

| error_code | 含义 |
|---|---|
| UNKNOWN_TOOL | 引用了未注册的工具 |
| INVALID_TOOL_ARGUMENTS | 参数不符合 ToolSpec.input_schema |
| TOOL_PERMISSION_DENIED | 工具或参数被 allowlist / 权限拒绝 |
| TOOL_EXECUTION_FAILED | 工具执行本身失败 |
| TOOL_RESULT_INVALID | 工具返回了不符合 output contract 的结果 |
| TOOL_BUDGET_EXCEEDED | 单工具预算（调用 / 错误）用尽 |
| AGENT_BUDGET_EXCEEDED | Agent 总预算（步数 / 调用数）用尽 |
| ACTION_PARSE_FAILED | Agent 的决策无法解析成合法 AgentAction |

关键原则：

> **Tool error ≠ Agent process crash。**

- 正常工具错误应形成**结构化 Observation**，让 Agent 有机会恢复；
- 只有**基础设施异常**（Runtime 崩溃、端口不可用、Schema 基础设施损坏等）才进入整体 `failed`；
- 一个工具失败不自动终结整个请求，也不自动重试。

---

## 10. Observation 安全与大小边界

Observation 不能无限大。至少规划：

- 结构化结果（不是原始 stdout / 全文 dump）；
- 结果条数上限；
- 单字段字符上限；
- 总 Observation size 上限。

**禁止进入 observation / trace**：

- API Key；
- Authorization 头；
- 环境变量 secret；
- raw system prompt；
- private CoT；
- traceback；
- 无限制全文；
- 本地敏感绝对路径。

（学习文档中允许使用抽象示例路径，不复制真实敏感路径。）

---

## 11. RunTrace 设计

复用 Gate 3 的思想：**Trace ≠ Chain of Thought**。

Gate 4 Trace 建议记录以下事件：

- `agent_started`
- `decision_completed`
- `tool_call_requested`
- `tool_call_validated`
- `tool_execution_completed`
- `tool_execution_failed`
- `budget_checked`
- `final_answer_completed`

可以记录：

- `tool_name`
- `call_id`
- `status`
- `error_code`
- safe counts（调用次数 / 错误次数）
- duration

**不要记录模型隐藏推理**。Trace 记录"发生了什么、每步用了哪些工具、结果如何、预算如何"，不记录模型为什么这么想。

---

## 12. 阶段路线（写死，不允许跳步）

Gate 4 冻结顺序：

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

- 只有 `G4-DESIGN-01` = IN PROGRESS；
- 其余全部 NOT STARTED；
- **不能提前声称已实现**。

---

## 13. 评测口径（本任务只设计，不创建 benchmark）

预注册以下维度：

| metric | 含义 |
|---|---|
| tool_selection_accuracy | 选择的工具是否与任务匹配 |
| argument_schema_validity | 参数是否符合 Schema |
| task_success_rate | 任务最终是否成功完成 |
| unnecessary_tool_call_rate | 不必要工具调用率（过度调用） |
| tool_error_recovery_rate | 工具出错后 Agent 的恢复率 |
| budget_violation_count | 预算违规次数 |
| loop_termination_rate | 循环正确终止率 |
| final_answer_grounding / evidence usage | 最终答案是否落在证据上 |

任务类型未来至少包括：

- `no_tool`（不需要工具，直接回答）；
- `single_tool`（单工具）；
- `multi_tool`（多工具协作）；
- `tool_error`（工具出错，需恢复）；
- `unanswerable / refusal`（应拒答或无法回答）。

明确口径：

> **最终不能只拿"Tool Call JSON 合法率"冒充 Agent 成功率。** JSON 合法只说明"格式对"，不说明"工具选对了、任务完成了、答案有证据"。

---

## 14. 非目标

Gate 4 严禁顺手做：

- LangChain Tool；
- OpenAI function calling 封装层；
- MCP；
- ReAct 字符串式；
- Graph Agent；
- multi-agent；
- memory；
- skill system；
- browser；
- shell；
- Docker；
- UI；
- CI。

不因为网上流行某个 Agent 框架就重写项目。

Gate 4 第一原则依旧是：

> 先把自己的 Tool Runtime 契约弄正确、可测、可解释。
