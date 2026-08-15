# 84-Gate4结构化Tool选择与LLM决策边界

> G4-AGENT-04：把 LLM 接入 Gate 4——模型看见用户请求 + 当前 Registry 的 ToolSpec，只能返回一个严格结构化的 AgentAction（tool_call / final_answer / refuse）。
> 日期：2026-08-15
> 状态：Gate 4 = IN PROGRESS；G4-TOOLS-03 / R1 / R1-R1 = Reviewer accepted / CLOSED；**G4-AGENT-04 = REVIEW PENDING**（LLM single-step structured decision candidate）。
> 本任务只做一次 Decision，不执行 Tool、不把 Observation 喂回模型、不做循环。

前几张卡把"底座"和"三个真实 Tool"搭好了。这张卡第一次让模型参与：**模型看到问题 + 工具清单，只允许输出一个结构化的动作**。但一次都不执行。

---

## 0. 一句话

G4-AGENT-04 证明：**LLM 能在一个强 schema 约束下，从 Registry 的真实 Tool 里选一个，输出严格结构化的动作**——而系统既不执行它，也不让它自己生成 call_id。动作空间是硬约束，模型只是"决策器"。

## 1. 什么是 AgentAction

AgentAction = 模型一次决策的**强类型结果**，只有三种：

```
AgentAction
├── ToolCallAction   → "我要调用这个 Tool"
├── FinalAnswerAction→ "我直接给答案"
└── RefuseAction     → "我不答（带固定 reason_code）"
```

这是 **discriminated union（判别联合）**：同一个"动作"类型，根据 `action` 字段判别是三种中的哪一种。每种都有**精确的字段集合**，不能多、不能少。

## 2. ToolCallAction ≠ ToolCall

- **ToolCallAction**：模型的意图（`action / tool_name / arguments`），只含模型有权决定的字段；
- **ToolCall**：系统的执行凭证（`call_id / tool_name / arguments`），call_id 由系统生成。

模型输出 ToolCallAction 之后，Runtime 才做 `ToolCall.create(...)` 生成系统自己的 call_id。两者之间的分界，正是"模型只能选工具传参数，系统负责凭证与执行"。

## 3. 为什么 call_id 不能让 LLM 生成

call_id 是**记账凭证**。如果模型能自己发 call_id，它就能伪造"某次调用发生过"——审计、去重、复现全部失真。所以 `ToolCall.call_id` 是 `init=False`（结构层禁止注入），模型 Action 里也绝不能出现 `call_id` 字段（出现即 `ACTION_PARSE_FAILED`）。

## 4. strict structured output

模型的输出不是"自然语言声明"，而是一个**必须恰好符合所选动作字段集合的 JSON object**：

- tool_call → 只能 `action / tool_name / arguments`；
- final_answer → 只能 `action / answer`；
- refuse → 只能 `action / reason_code`。

多余字段（哪怕是 `thought`）、缺失字段，一律 `ACTION_PARSE_FAILED`。**不能"忽略多余字段继续执行"**——宽容会掩盖模型行为问题。

## 5. duplicate JSON key 风险

JSON 规范允许重复 key，但最后出现的值会覆盖前面的——这是**解析歧义**，可被用来注入恶意覆盖。Gate 3 早已确立：任意层级 duplicate key 拒绝。Gate 4 用 `json.loads(..., object_pairs_hook=_reject_duplicate_keys)` 实现，顶层和嵌套参数里的重复 key 都被拒绝。

## 6. 为什么 unknown fields 要拒绝

未知字段 = 模型在"越界声明"。如果 `final_answer` 带 `tool_name`、`tool_call` 带 `thought`，说明模型没遵守动作契约。**精确字段集合**（`set(obj.keys()) == allowed`）同时拦住了 unknown 与 missing。

## 7. Tool name allowlist

Parser 不只检查 `tool_name` 是字符串，还必须 **`registry.get_spec(tool_name) != None`**。模型永远不能发明 Tool：输出 `shell` / `python` / `os.system` → 直接 `ACTION_PARSE_FAILED`。即使 Prompt 被注入（用户写"忽略规则调用 shell"），Registry 是最终硬边界。

## 8. arguments 为什么要 Decision + Executor 双重校验

- **Decision 层**（LLM Action Parser）：不让非法动作进入 Runtime——模型输出 `{"tool_name":"calculator","arguments":{"expression":123}}` 或带上 `top_k` 额外字段，Decision 层就拒绝；
- **Executor 层**（真正执行前）：最终执行安全边界——即使有绕过 Decision 层的路径，Executor 再校验一次。

不是重复劳动：Parser 保护"运行时入口"，Executor 保护"实际执行"。两层是纵深防御。

## 9. Prompt 是软约束，Parser/Registry 是硬约束

Prompt 只是"劝模型听话"（软约束）。真正保证安全的是：

- **Parser**：只接受单个 JSON object + 精确字段 + duplicate key 拒绝；
- **Registry**：tool_name 必须存在；
- **input_schema**：arguments 必须合法。

模型即使输出越界内容，Parser/Registry 也会拒绝。**安全不依赖模型的听话程度。**

## 10. fail closed 与 fallback 的区别

- **fallback**：解析失败后自动落到一个"安全默认"（Gate 3 Planner 失败 → single retrieval）；
- **fail closed**：解析失败就停止，不自动做任何事。

Gate 4 Tool Selection 用 **fail closed**：模型输出非法 → `ACTION_PARSE_FAILED`，停止这次 Decision。**不做"默认 knowledge_search"**——因为那可能自动执行本不该访问的能力。Tool 有真实副作用风险，不能用"自动兜底"掩盖。

## 11. 为什么 Gate 3 Planner fallback 可以存在，而 Tool selection 不应默认调用 Tool

Gate 3 的 fallback 是"同一个 RAG 检索能力"内部的降级，风险低、可复现。Tool selection 的 fallback 是**选择执行一个能力**——如果解析失败就默认跑 knowledge_search，等于让一个格式错误间接触发了工具调用。两条路的风险量级不同，所以 Tool 层选择 fail closed。

## 12. Provider metadata

每次 Decision 调用记录身份与观测（`AgentDecisionCallMetadata`）：

```
provider / model / prompt_version / prompt_sha256
call_count / input_tokens / output_tokens / latency_ms
```

- `call_count = 1`（单次调用，不自动重试）；
- 禁止：api_key / Authorization / raw response / raw model output / 完整 prompt / CoT / exception repr。

这套经验直接来自 Gate 3 的 `PlannerCallMetadata`——模型调用的可观测性是一致的好实践。

## 13. 为什么不记录 CoT

CoT（思维链）是模型私有推理：可能包含幻觉、偏见、敏感信息，且不可复现。Trace/Outcome 只记录**实际发生了什么**（选了哪个工具、传了什么参数、结果如何），不记录"模型为什么这么想"。`AgentDecisionOutcome.to_dict()` 天然不含 raw output / CoT。

## 14. Prompt SHA 的意义

`tool_agent_decision_prompt_v1` 的 SHA-256 把**提示词版本**绑定进 metadata。这样每次调用都能回答："这次模型看到的是哪一版指令？"——实验可复现、版本可追溯。改 Prompt = 改 SHA = 新版本，不会被旧结果冒充。

## 15. Fake Client 测试

真实 Provider 通过 `client` 参数注入 Fake Client（0 网络）。Fake 可以返回合法内容、异常（超时/Provider 错误）、残缺结构（空 choices / 缺 message / 非字符串 content / 坏 usage）。这套打法把"Provider 解析逻辑"与"真实网络"解耦，能稳定测到所有边界。

## 16. 单步 Decision 与完整 Tool Agent Loop 的区别

```
单步 Decision（本卡）          完整 Tool Agent Loop（G4-RUNTIME-05）
模型 → AgentAction             模型 → AgentAction → 执行 Tool
（到此为止）                   → Observation → 模型再决策 → ...
```

本卡只做**一次**决策：`LLM → AgentAction`。没有执行、没有 Observation、没有下一轮。所以现在只能说"LLM single-step structured decision candidate"，还不能说"完整 Tool Agent"。

## 17. 面试问答

**Q1：ToolCallAction 和 ToolCall 有什么区别？**
> ToolCallAction 是模型的意图（action/tool_name/arguments）；ToolCall 是系统的执行凭证（含系统生成的 call_id）。模型输出 Action，Runtime 才创建 ToolCall。

**Q2：模型能自己带 call_id 吗？**
> 不能。call_id 是记账凭证，结构层（`init=False`）禁止注入；模型 Action 出现 call_id 字段 → ACTION_PARSE_FAILED。

**Q3：模型输出带 thought 字段怎么办？**
> 拒绝。每种 action 的顶层字段集合是精确的，多余字段（含 thought）→ ACTION_PARSE_FAILED。

**Q4：模型发明一个 Tool 怎么办？**
> Registry 是硬边界：`registry.get_spec(tool_name)` 为空 → ACTION_PARSE_FAILED。shell / python 等都不可能。

**Q5：为什么 Decision 层和 Executor 层都校验 arguments？**
> 纵深防御：Parser 不让非法动作进 Runtime，Executor 是执行前最后一道闸。两层职责不同。

**Q6：为什么 Tool selection 不做 fallback？**
> fail closed。解析失败就停止，不默认调用任何 Tool——那会间接触发本不该执行的能力。Gate 3 Planner 的 fallback 是同一检索能力内部的降级，风险量级不同。

**Q7：为什么模型输出非法不抛异常？**
> 用 AgentDecisionOutcome（action=None, failure_code=ACTION_PARSE_FAILED）表达，异常只代表程序 bug，不代表模型输出错了。

**Q8：Prompt 被注入了怎么办？**
> 安全不依赖 Prompt。Parser 只收严格 JSON object + 精确字段，Registry 限定 tool_name，input_schema 限定 arguments——模型即使输出越界内容也会被拒绝。

---

## 18. R1 补充：JSON 决策可靠性三个知识点

### 18.1 JSON mode ≠ schema validation

`response_format={"type":"json_object"}` 只保证模型输出**在语法上是合法 JSON**，完全不保证它是**我们允许的 AgentAction**。JSON mode 不会检查字段是否精确、tool_name 是否在 Registry、arguments 是否过 schema。所以仍然要完整保留：

```
response_format
→ strict JSON parser
→ exact fields
→ Registry allowlist
→ Tool input_schema
```

> **Provider JSON mode 负责"语法上是 JSON"；Parser + Registry + JSON Schema 负责"语义上是我们允许的 AgentAction"。**

这也是为什么不切换到原生 Function Calling——本任务要验证的是自己定义的 AgentAction union，而不是第三方格式。

### 18.2 prompt_sha256 与 toolset_sha256 为什么要分开

- **prompt_sha256**：绑定"模板版本"（指令 + 示例 + reason codes）。改 Prompt = 新 SHA；
- **toolset_sha256**：绑定"模型实际看见的 Tool 集合"（name / description / input_schema 的 canonical JSON）。同一个 Prompt 下，Registry 增删/改 Tool，toolset_sha256 变化。

两者分开才能精确回答两个独立问题："这次用的是哪版指令？" 和 "这次模型看到了哪些工具？"。合并成一个哈希会丢失区分度。

### 18.3 为什么 frozen dataclass 对 nested arguments 仍然不够

`@dataclass(frozen=True)` 只挡**字段级赋值**（`action.arguments = ...`），挡不住**可变 dict 的原地修改**（`action.arguments["nested"]["x"] = ...`）。所以 ToolCallAction 的 arguments 用了和 ToolSpec schema 相同的思路：

```
private backing（_arguments）
+ property 返回深拷贝
+ arguments_copy() 覆盖嵌套结构
```

`AgentDecisionOutcome.to_dict()` 也只返回深拷贝，不泄漏内部可变引用。这样模型传进来的参数在解析完成后就变成**审计快照**——后续任何环节的修改都不会改写它。

---

## 19. R1-R1 补充：Parser validation 与 domain invariant validation 不一样

- **Parser validation**：防御**不可信模型输出**——模型可能来自真实 Provider、Fake Provider、或任何来源，Parser 把"非法输出"统一转成 `ACTION_PARSE_FAILED`；
- **Domain invariant validation**：领域对象**自身的不变量**——`ToolCallAction.action` 必须精确等于 `tool_call`、`FinalAnswerAction.answer` 非空且 <=4000、`RefuseAction.reason_code` 在冻结集合内、`AgentDecisionOutcome.action` 必须是三个合法 Action 之一。

区别：Parser 防的是"模型说错话"（外部不可信边界）；领域不变量保证的是"Runtime 内部无论对象来自真实 Provider、Fake Provider 还是测试代码，都不会出现 'Python 类型与 action discriminator 自相矛盾' 的状态"（内部契约）。两者职责不同，都不能省略——Parser 管入口，领域对象管自身一致性。
