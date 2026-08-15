# 83-Gate4三个真实Tool与Adapter设计

> G4-TOOLS-03：把三个真实 read-only Tool（calculator / code_search / knowledge_search）接入已验收的 ToolSpec → RegisteredTool → ToolRegistry → ToolExecutor。
> 日期：2026-08-15
> 状态：Gate 4 = IN PROGRESS；G4-TOOL-02 / R1 = Reviewer accepted / CLOSED；**G4-TOOLS-03 = REVIEW PENDING**（3 个真实 read-only Structured Tools implemented candidate）。
> 契约权威：`docs/design/g4_structured_tool_agent.md`；本任务 0 LLM Tool Selection / 0 Tool Loop / 0 API / 0 AgentAction / 0 Holdout。

上一篇（笔记 82）证明了"底座能安全注册并执行一个 Tool"。这篇讲：**三个真正不同的能力，怎么都变成统一的可安全执行的 Tool**。

---

## 0. 一句话

calculator（算数字）、code_search（找代码）、knowledge_search（查知识库）——三种完全不同的能力，通过同一个 ToolSpec + ToolHandler 模板注册进 Registry，由同一个 Executor 校验、授权、执行、收口成 ToolObservation。**异构能力，统一契约。**

## 1. Tool core 和真实 Tool 的区别

- **Tool core（G4-TOOL-02）**：ToolSpec / ToolCall / ToolObservation / Registry / Executor 这些通用设施。它不知道"算数"或"搜代码"是什么；
- **真实 Tool（G4-TOOLS-03）**：在 core 之上提供具体的 ToolSpec（声明）+ ToolHandler（实现）。

core 负责"怎么安全地执行"，真实 Tool 负责"执行什么"。两者解耦：加一个新 Tool 只需要写一个 Spec + 一个 Handler，Executor 一行不改。

## 2. 为什么 Calculator 要 AST 而不是 eval

`eval("12 * (3 + 4)")` 最省事，但等于**把任意 Python 表达式当代码执行**。`eval("__import__('os').system('rm -rf /')")` 就能删文件。

正确做法：`ast.parse(expression, mode="eval")` 把表达式解析成**语法树**，然后只允许白名单节点：

- 数字常量；
- `+ - * / // % **`；
- 一元 `+ -`；
- 括号（AST 里括号是隐含的，不需要单独节点）。

任何其它节点（名字、属性、函数调用、下标、lambda、字符串、容器、comprehension）**直接拒绝**。

再加三道防线防 DoS：

- **AST 节点数上限**（50）；
- **幂指数上限**（0~1000，防 `999999 ** 999999` 这类计算爆炸）；
- **结果必须有限**（float 的 NaN/Inf 直接拒绝）。

这就是"白名单 evaluator"：不是"放行已知安全"，而是"只放行已知安全，其余全拒"。

## 3. 什么是 capability adapter

Adapter（适配器）= 把"已有能力"改造成"统一契约的 Tool"的那一层。

- knowledge_search 把 **RetrievalPort**（Gate 3 已有）适配成 ToolHandler；
- code_search 把 **文件系统只读扫描** 适配成 ToolHandler；
- calculator 把 **AST evaluator** 适配成 ToolHandler。

Adapter 的价值：**复用已验证的底层能力，不改动底层实现**。Gate 3 的检索算法、冻结 runtime 都原样保留，Gate 4 只是在上面加了一层"工具外壳"。

## 4. knowledge_search 为什么复用 RetrievalPort

Gate 3 已经有一个统一的检索契约：

```python
class RetrievalPort(Protocol):
    supported_strategies: tuple[str, ...]
    def search(self, query, strategy, top_k) -> Sequence[Document]: ...
```

还有生产实现 `PipelineRetrievalAdapter`（把 Retriever 映射成 Runtime Document）。Gate 4 的 knowledge_search **不重建 Retriever、不建索引、不复制检索算法**——直接注入一个 RetrievalPort，handler 只调 `port.search(...)`。

这正是设计文档说的：**Gate 3 frozen runtime 作为能力复用，不被 Gate 4 反向改写**。knowledge_search 是"检索能力的工具入口"，不是"第二个检索系统"。

## 5. 为什么模型不能控制 top_k / strategy

如果模型能传 `top_k=100000` 或 `strategy="hybrid"`，它就能：

- 把检索量开到爆炸（成本 / 延迟 / 上下文超限）；
- 绕过系统既定的检索策略（比如本该只走 bm25，它改成 hybrid）；
- 影响实验/评测的身份一致性。

所以 knowledge_search 的 input_schema **只允许 query**：`additionalProperties: false` 让模型多传任何字段都直接 `INVALID_TOOL_ARGUMENTS`。`strategy`（bm25）和 `top_k`（5）是 Handler **构造时**写死的系统配置，模型接触不到。

如果注入的 port 不支持配置的 strategy？**不偷偷换策略**——明确执行失败（`TOOL_EXECUTION_FAILED`），让上层看到"这个检索后端不支持 bm25"。

## 6. code_search 如何形成 filesystem sandbox

code_search 的安全模型很直白：**模型根本没有文件系统路径**。

- input 只接受 `{"query": "PipelineRetrievalAdapter"}`，不接收任何 path；
- repo_root 由系统构造 Handler 时注入；
- 只扫描固定允许目录（core / api / evaluation / scripts / tests / docs）与固定后缀（.py / .md / .json / .yaml / .yml / .toml / .txt）；
- 跳过隐藏目录、`__pycache__`、`.venv`、`node_modules` 等、`.env` 与 secret/credential 文件；
- 超大文件（>1MiB）不读，不可读文件安全跳过；
- 输出 path 用 `relative_to(root).as_posix()` → **repo-relative POSIX，绝不返回绝对路径**。

这样"路径逃逸"这种攻击面根本不存在——模型连路径都传不了。

## 7. literal search 和 regex search 的权衡

- **literal substring search**：确定、可复现、无 ReDoS 风险、行为可预测。query 就是"这段文字里有没有这个子串"；
- **regex search**：强大，但引入正则注入、ReDoS（灾难性回溯）、语法错误处理、实现复杂度。

v1 选 **case-insensitive literal search**：够用（找类名/符号/配置串），且把"搜索行为"变成完全确定性。以后确实需要正则再单独立项，保持单变量演进。

## 8. 为什么 Tool output 必须受限

Tool 是 evidence 提供方，不是生成器。输出如果无限，模型上下文会爆、Trace 会失控、敏感信息会泄漏。所以：

- knowledge_search 的 snippet 单条 **<=500 字符**，不返回完整正文；
- code_search 的 text 单条 **<=300 字符**，path 相对、无绝对路径；
- 所有输出都过 output_schema 校验 + `json_deep_copy`（JSON-safe + 脱离引用）。

**输出受限 = 输入可控的另一半**。只堵输入不堵输出，信息照样能漏。

## 9. ToolSpec 与 Handler 怎样配对

```
RegisteredTool
├── spec: ToolSpec        ← 模型可见声明（name/description/schemas/version）
└── handler: ToolHandler  ← 系统私有实现（execute）
```

配对的唯一入口是 `ToolRegistry.register(spec, handler)`。`get_spec / list_specs` 只给模型看 spec；handler 只在 Executor resolve 后由系统调用。三个 Tool 用同一套配对机制，这就是"统一契约"。

## 10. 三个 Tool 为什么能证明"异构 Tool"能力

| Tool | 底层能力 | 依赖注入 |
|---|---|---|
| calculator | AST 白名单求值 | 无 |
| code_search | 文件系统只读扫描 | repo_root |
| knowledge_search | 检索（RetrievalPort） | retrieval_port |

三种底层机制（纯计算 / 文件系统 / 外部检索）完全异构，但都能：

1. 定义成一个 ToolSpec（schema 可校验）；
2. 绑定一个 ToolHandler（系统私有）；
3. 注册进同一个 Registry；
4. 由同一个 Executor 走同一条流水线收口成 ToolObservation。

这证明 Structured Tool core 是**能力无关的通用底座**，不是某个工具的专用代码。

## 11. 为什么现在仍不能叫"完整 Tool Agent"

现在是 **3 个真实 read-only Structured Tools implemented candidate**，还不是 Tool Agent。因为还缺三件事：

- **Tool Selection**：模型还不能在工具之间做选择（0 LLM Tool Selection）；
- **Observation-driven decision**：还没有"看到 Observation 后决定下一步"；
- **Tool Loop**：还没有"决策 → 执行 → 观测 → 再决策"的循环。

这些是 G4-AGENT-04 / G4-RUNTIME-05 的范畴。简历上诚实写："实现了 3 个可安全注册、校验、执行的只读 Tool"，不写"已实现 Tool Agent"。

## 12. 面试问答

**Q1：eval 和 AST allowlist 求值有什么区别？**
> eval 把表达式当任意 Python 代码执行（有 `__import__`、系统调用等风险）；AST 求值先解析成语法树，只放行白名单节点（数字 / 四则 / 幂 / 一元 / 括号），其余节点直接拒绝，并叠加节点数、幂指数、有限结果三道 DoS 防线。

**Q2：knowledge_search 为什么不自己 new 一个 Retriever？**
> 因为 Gate 3 已有统一的 RetrievalPort 契约和生产 Adapter。复用端口 = 复用已验证的检索能力 + 不重复造轮子 + 不动 Gate 3 冻结 runtime。Gate 4 只加"工具外壳"。

**Q3：模型能传 top_k 或 strategy 吗？**
> 不能。input_schema 只允许 query（additionalProperties:false），strategy/top_k 是 Handler 构造时系统写死的配置。多传字段 → INVALID_TOOL_ARGUMENTS。

**Q4：code_search 怎么防止路径逃逸？**
> 模型根本没有路径参数，只能传 query 子串。repo_root 系统注入，只扫固定允许目录/后缀，输出用 relative_to 保证 repo-relative POSIX。攻击面直接不存在。

**Q5：为什么 v1 用 literal search 不用 regex？**
> literal 是确定性、可复现、无 ReDoS 风险；regex 强但引入注入、灾难性回溯与复杂度。v1 先保证确定性与安全，需要时再单变量加。

**Q6：Tool 输出为什么要受限？**
> 输出无限会撑爆模型上下文、失控 Trace、泄漏敏感信息。snippet<=500、text<=300、无绝对路径，配合 output_schema + JSON-safe 深拷贝，保证信息只出不漏、只够用。

**Q7：三个异构 Tool 怎么统一？**
> 各自 = 一个 ToolSpec + 一个 ToolHandler，经 register 进同一个 Registry，由同一个 Executor 走同一条流水线。能力无关的底座，再加具体实现。

**Q8：为什么还不能说实现了 Tool Agent？**
> 还缺 Tool Selection、Observation-driven decision、Tool Loop。现在是"可安全执行工具的底座 + 3 个真实只读工具"，不是"模型自主选工具的 Agent"。
