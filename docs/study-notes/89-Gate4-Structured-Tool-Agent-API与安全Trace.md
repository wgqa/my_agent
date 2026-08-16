# 89. Gate 4 Structured Tool-Agent API 与安全 Trace

> G4-E2E-07A：把已验收的 Structured Decision → ToolAgentRuntime → 三个只读 Tool →
> Observation → Final/Refuse 接成正式 HTTP API（`POST /tool-agent/query`）。
> 本任务 0 DeepSeek，测试全用 Fake/Scripted Provider + Real Tool。

---

## 0. 一句话

API 是 Runtime 的"窗户"：它只该暴露**结构化安全事实**，把"系统边界"（budget /
provider / tool allowlist）锁在服务端，把"模型内部"（CoT / raw / prompt）挡在响应外。

## 1. Gate3 /agent/query 与 Gate4 /tool-agent/query 的区别

| | /agent/query（Gate 3） | /tool-agent/query（Gate 4） |
|---|---|---|
| 链路 | Planner → Retrieval → Generator → Citation | Decision → Tool → Observation → Final |
| 测什么 | 问题分解 + 检索 + 引用 | Tool 选择 + 参数 + 多步 + 拒绝/终止 |
| Runtime | Gate 3 AgentRuntime（agent_runtime 全局） | ToolAgentRuntime（独立 tool_agent_runtime 全局） |
| 预算 | Retrieval 调用预算 | 5/4/2（iterations/tool_calls/tool_errors） |

两个端点语义完全不同，**各用各的 runtime 全局变量**，绝不互相覆盖。

## 2. 为什么不能共用同一个 runtime 全局变量

- 生命周期不同：Gate 3 runtime 依赖 Planner/Generator；Gate 4 依赖只读 Tool Registry；
- 一个全局变量若被两个端点共用，一个端点初始化失败会拖垮另一个；
- 职责不同：共享会引入"Retrieval 预算被 Tool Loop 吃掉"之类的串扰。

所以 `api/app.py` 里 `agent_runtime` 和 `tool_agent_runtime` 是两个独立全局，
lifespan 里各自 try/except 初始化。

## 3. API 为什么不能开放 budget / provider / tool allowlist

- **budget（5/4/2）** 是系统硬约束，评测与控制变量的前提；调用者改了 budget，跑出来的
  就不是"同一套 Runtime"；
- **provider/model** 是正式配置身份；让调用者换模型 = 让结果身份失效；
- **tool allowlist** 决定模型能力边界；开放它 = 让外部决定"模型能碰什么"。

v1 请求 `ToolAgentQueryRequest` 用 `model_config={"extra": "forbid"}`：**未定义字段
（含 history / provider / model / budget 等）一律 422 显式拒绝**，绝不静默忽略。

## 4. HTTP transport error 与 Agent structured failure 的区别

- **Agent structured failure**（refused / failed / parse failure / budget stop）是
  Runtime **正常返回**的结构化结果——它不是 HTTP 错误，**应该 HTTP 200**，body 里带
  `status/reason_code/failure_code`；
- **HTTP transport / 基础设施错误**（Provider 网络异常、未初始化、未知异常）才是
  真正的错误——`503`（未初始化）/ `500`（未知基础设施异常）。

代码上：`rt.run(question)` 返回 `ToolAgentRunResult`（含所有 Agent 结果）；只有
`run()` 内部抛出的未知异常才被 catch → 500。**绝不把 refused/failed 误转成 500**，
否则客户端无法区分"Agent 正常拒绝"和"服务坏了"。

## 5. 为什么 refused / parse failure / budget stop 仍可 HTTP 200

它们是**系统行为的观测**，不是系统故障：

- `refused`：模型正确拒绝（该做的事）；
- `parse failure`：模型输出不合法被 Parser 拦住（不好的但可观测的行为）；
- `budget stop`：模型跑不完撞预算（可观测的收敛性问题）。

把这三者都当 200 结构化结果，客户端才能分析"Agent 到底怎么了"，而不是笼统看到一个
500。

## 6. safe trace ≠ CoT

- **Trace**：Runtime 的 `RuntimeTraceEvent`，只记"发生了什么"（event_type /
  iteration / tool_name / status / error_code），已脱敏；
- **CoT**：模型的推理链（reasoning_content / thought），是模型内部，不暴露。

API 返回的 trace 走**字段白名单**（`_safe_trace`），只透出上面这些安全字段；
**绝不**返回 raw model output / 完整 Prompt / reasoning_content / traceback /
本机敏感绝对路径。`code_search` 的命中行文本也不进 trace——否则一次搜索就泄漏整个
源文件。

## 7. 为什么 Tool Observation 是 untrusted data

Tool 返回的内容（检索到的文档、代码匹配行、计算结果）都可能被注入指令（Prompt
Injection）。Runtime 把 Observation 作为**不可信数据**回喂决策循环，不拼进 system
role。API 层同样不能把 Observation 原文原样回给用户当作可信内容——trace 只透安全字段。

## 8. Fake Provider + Real Tool 的 E2E 集成测试价值

用 **Scripted Provider** 驱动**真实 Tool** 走完整 API：

- 证明"接线没断"：Runtime 真的调了 Calculator/CodeSearch/KnowledgeSearch handler；
- 证明"Observation 真的反馈"：multi-step 测试里第二个 Decision 从 context 读出
  `4096` 才决定下一步；
- 证明"错误边界正确"：parse failure / budget stop → HTTP 200、未初始化 → 503、
  非法请求 → 422；
- 证明"安全"：响应序列化无 key / raw / CoT / prompt / traceback。

**即使一个真实模型都不调**，也能验证 API 层完全正确。

## 9. 为什么 baseline 后先接 API，而不是马上针对 Dev 调 Prompt

- baseline（06B-02）暴露的问题（parse failure ×2、budget stop ×1、multi-step 少步）
  属于**系统行为观测**，先接入 API 让这些行为变成**可复现、可观测、可排查**的接口；
- 直接改 Prompt 会破坏 E2E 控制变量，而且没有可观测的传输层就无法对比"改前后行为"；
- 所以顺序是：**接 API（本卡）→ 之后若有必要再评估 Prompt 改动**，而不是把 API 和
  Prompt 调优搅在一起。

## 10. 边界与后续

- 本任务 0 real LLM / 0 formal benchmark / 0 Prompt change / 0 Tool/Runtime 行为改动；
- g4q013/g4q018/g4q019/g4q020 的 baseline 失败作为**已知 limitation**记录，不借 API
  修（不扩大 budget、不加"必须继续调用第二工具"提示、不加自动 retry）；
- 后续：E2E 打通真实 API 调用、G4-CLOSE。
