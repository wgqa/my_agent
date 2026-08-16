# 91. Gate 4 最终冻结与 Structured Tool-Agent 项目总结

> G4-CLOSE-08：Gate 4 最终冻结。这篇从零讲清楚 Structured Tool Agent 是什么、
> 为什么这么设计、正式结果怎么解读、以及校招面试怎么讲。权威数字见
> `docs/experiments/gate4_freeze.json`（gate4_system_freeze_id=96c159b1ca2c）。

---

## 1. Gate 4 到底解决什么问题

Gate 1-3 解决"检索/生成/引用"的正确性与可评测；Gate 4 进入**Agent 层**：让模型不只是
"答一道题"，而是"为完成任务去调用工具"。问题变成：**模型凭什么调用工具、怎么调、
调错怎么办、跑不完怎么办**——这些都需要强类型契约与评测，而不是让模型自由发挥。

## 2. ToolSpec / ToolCall / ToolObservation 是什么

- **ToolSpec**：工具的"能力声明"（名字、描述、输入/输出 JSON Schema）。模型看到它才知道
  有什么工具、怎么传参；
- **ToolCall**：模型发出的"我想调用某工具 + 这些参数"的结构化请求（含系统生成的 call_id）；
- **ToolObservation**：工具执行后的**结构化结果**（status + result/error），是回喂给下一
  次 Decision 的**不可信数据**。

三者都是数据，不是可执行代码。

## 3. Registry 和 Executor 为什么分离

- **Registry**：登记"有哪些工具 + 各自 handler"（能力目录）；
- **Executor**：拿到 ToolCall → 查 Registry → 校验参数 → 真正执行 → 产出 Observation。

分离的意义：**"模型看到的能力" 必须 == "系统实际执行的能力"**。若模型看到的工具列表和
实际执行注册表不一致，就会"模型以为有 shell、系统其实没有"。所以 Runtime 强制 Decision
和 Execution 用同一个 Registry，封死"能力分裂"。

## 4. LLM Decision 与 Runtime 谁控制什么

- **LLM（Decision Provider）**：只负责"下一步做什么"——final_answer / tool_call /
  refuse，以及工具名和参数（**都是不可信的**）；
- **Runtime**：负责预算、重复调用检测、参数校验、工具执行、Observation 回喂、Trace、
  终止。**Runtime 是唯一的系统边界 owner**。

模型说"调用 shell 执行 rm"只是建议；有没有 shell、允不允许，由 Registry + 应用层决定。

## 5. 为什么预算必须系统控制

`max_agent_iterations=5 / max_tool_calls=4 / max_tool_errors=2` 是系统硬预算，LLM 无权
看、无权改。原因：

- 预算失控 = 无限循环/无限调用 = 成本与可用性灾难；
- 预算可变 = 同一套评测失去控制变量（谁改了预算谁的成绩就没法比）；
- API 层也不开放 budget（`extra=forbid`），调用者不能覆盖。

## 6. 为什么 Observation 是 untrusted data

Tool 返回的内容（检索到的文档、代码匹配行、网页文本）可能被注入恶意指令（Prompt
Injection）。Observation 是**外部数据**，不是系统指令——Runtime 把它作为不可信数据回喂
决策循环，不拼进 system role，应用层仍校验工具参数与权限。

## 7. 为什么 safe trace 不是 CoT

- **Trace**：Runtime 记录"发生了什么"（event_type / iteration / tool_name /
  status / error_code），脱敏、结构化；
- **CoT**：模型的内部推理（reasoning_content / thought），属于模型私有。

API 返回的 trace 走字段白名单，绝不包含 CoT / raw output / prompt / key / traceback。
`code_search` 的命中行正文也不进 trace，否则一次搜索就泄漏源文件。

## 8. Tool error / parse failure / refusal / budget stop 区别

| 现象 | 是什么 | 系统语义 |
|---|---|---|
| Tool error | 工具执行失败（参数非法/运行时异常） | 可恢复但 2 次封顶（TOOL_EXECUTION_FAILED） |
| parse failure | 模型输出不合法被 Parser 拦住 | ACTION_PARSE_FAILED，不是好行为 |
| refusal | 模型主动拒绝（含原因码） | 正确行为（UNSUPPORTED/UNSAFE/INSUFFICIENT） |
| budget stop | 模型跑不完撞预算 | AGENT_BUDGET_EXCEEDED（收敛性问题） |

refused/parse/budget 都是**结构化系统结果** → API HTTP 200；只有未知基础设施异常 → 500。

## 9. 两阶段 Gold 隔离

- **Phase A 执行**：模型只见 `query + ToolSpec + observations`；execution artifact 只
  存安全事实（case_id/status/answer/counters/trace/decision 摘要），无任何 Gold-only
  字段；
- **Phase B 评测**：重新加载冻结 Gold，离线评分，case_id 集合精确相等校验。

防止"模型看到 expected tool 变成开卷考"。

## 10. 为什么评测 Runner 自己也要审计

评测器是"判分的人"：它漏 Gold、算错口径、跳过 gate，分数就失真。所以 Runner 本身有
0-LLM harness（Fake Provider + Real Tool）把状态机跑通，并有 preflight gates
（tracked clean / dataset identity / corpus provenance / code-gold diff / no-overwrite /
授权）。"造尺子的尺子"也要可信。

## 11. 15 项 Tool-Agent metric 各自说明什么

- first_action / first_tool：该不该用工具、用对没；
- required_tool_coverage：该用的工具（micro obligation）用了几个；
- task_completion / termination：终态 + 断言 / 终态 + reason；
- final_answer_correct：deterministic assertion proxy（不等于语义正确）；
- unnecessary / forbidden：过度工具化 / 碰了不该碰的工具；
- duplicate / budget_stop / parse_failure：重复、跑不完、输出不合法；
- allowed_sequence_match：multi-step 是否命中合法序列；
- average_iterations / tool_calls / tool_error_rate：效率与稳定性；
- 每项都带 numerator/denominator/value，denominator=0 → null 不撒谎。

## 12. 正式 baseline 20/24 应怎样解读

task_completion 20/24 = 0.833：24 条里 20 条"终态对 + 断言过"。这**不是**"模型 83% 答对"，
而是"在 5/4/2 预算下 20 条按 Gold 走完"。4 条没完成各有不同原因（parse ×2、少步、
撞预算）——分开看才知道问题在哪。

## 13. 为什么 multi-step 1/4 不等于项目失败

allowed_sequence_match 1/4：4 条 multi-step 只有 g4q017 完美走链
（code_search→calculator）。其余三条失败方式完全不同：

- g4q018：只 code_search 没算（半途而废）；
- g4q019：完全没调工具（想直接答 + parse fail）；
- g4q020：code_search 反复 4 次撞预算。

这暴露的是**当前模型的决策层 limitation**（不收敛、不会规划多步），不是系统架构坏了。
把它当作已知 limitation（L1）记录，是正式观测，不是项目失败。

## 14. HTTP API 如何把工程能力暴露给用户

`POST /tool-agent/query`：用户发 question，得到 status/answer/reason/failure/counters/
safe trace。API 把"Agent 结构化结果"和"HTTP 传输错误"分开（200 vs 500/503），让调用方
能分析"Agent 到底怎么了"，同时不泄漏模型内部/密钥/源文件。

## 15. Fake Provider + Real Tool 与 Real DeepSeek E2E 各证明什么

- **Fake Provider + Real Tool（07A）**：证明**接线与状态机正确**——0 网络也能验证
  Runtime 真调了 handler、Observation 真反馈、错误边界与安全 trace 都对；
- **Real DeepSeek E2E（07B）**：证明**生产链路真的通**——真实 HTTP → FastAPI →
  production Runtime → deepseek 决策 → 真实工具 → 后续决策 → 安全响应（6 条 smoke 全
  200 结构化）。

两者互补：前者可离线反复验证，后者证明真实环境可用。

## 16. 项目当前 limitation

- L1：multi-step allowed sequence match 1/4；
- L2：required tool coverage 14/20；
- L3：ACTION_PARSE_FAILED 2/24；
- L4：AGENT_BUDGET_EXCEEDED 1/24；
- L5：S4 knowledge_search 执行成功但当前索引知识未直接提供 RRF 证据；
- L6：07B 记录器崩溃导致一次 identical 6-case 证据重放（非 benchmark 重跑、非结果选择）。

这些是 **known limitations**，不是"等待偷偷修复的 bug"。

## 17. 为什么没有为了 24 条 Dev 刷到满分

- Dev 数字一旦被"记住"（overfit），Holdout 就失去意义；
- 现场调参（改 Prompt / 扩 budget / 加"必须继续调用第二工具"提示 / 自动 retry）会破坏
  E2E 控制变量；
- 所以正式基线差就如实记录；要改进走正式实验流程，且旧结果保留。

## 18. 面试时如何用 2 分钟讲 Gate 4

1. 一句话：给 RAG 加 Agent 能力——让模型按强类型契约调用只读工具完成任务；
2. 三件套：ToolSpec（能力声明）/ ToolCall（调用请求）/ ToolObservation（不可信结果）；
3. 系统边界：预算 5/4/2 系统控制、Registry=Executor 同源、Observation 不可信、safe
   trace≠CoT；
4. 评测：24-case Tool-use Dev benchmark（task completion 20/24），两阶段 Gold 隔离 +
   Runner 自己也被测试；
5. 工程：FastAPI `POST /tool-agent/query` + 真实 DeepSeek E2E 6 条 smoke 全 200。

## 19. 面试官追问 multi-step 弱点时怎么回答

"对，multi-step 是我们的已知 limitation（sequence match 1/4）。4 条里 g4q017 走对了
code_search→calculator；另外三条分别是'找到但没算''完全没调工具''反复查同一工具撞
预算'。这暴露的是当前模型的规划/收敛能力不足，不是架构问题——我们把它当作正式观测
记录，不现场调参去刷分，下一步会评估 Prompt/决策策略的改进。"

## 20. Gate 5 接下来还需要什么

Gate 5 = 端到端评测与工程收口（尚未开始）：CI/Docker、依赖锁定、可观测、UI、更广的
真实评测与公开演示。不要把 Gate 5 偷偷开始。

---

## 简历怎么写（建议口径）

> 构建强类型 Structured Tool Agent，支持 calculator / code search / knowledge
> search 三类只读工具；实现 5/4/2 有界 Agent loop、工具权限与参数校验、重复调用保护、
> 结构化 Observation 与安全 Trace；建立 24-case Tool-use Dev benchmark，正式基线
> task completion 20/24，并通过真实 FastAPI + DeepSeek 完成多工具 E2E 演示。

**不要写**："Tool Agent 100% 准确"。
**不要隐藏**：multi-step sequence match 1/4——面试时解释这是当前模型决策层 limitation，
正式观测记录，不现场调参。

## 收尾

- Gate 4 = CLOSE CANDIDATE / pending Reviewer（执行 Agent 不自写 CLOSED）；
- 冻结证据：`gate4_freeze.json`（freeze_id=96c159b1ca2c）、
  `gate4_tool_use_dev_baseline.json`、`gate4_tool_use_dev_seal.json`；
- 交接：`docs/HANDOFF.md`（不要重跑 fa4ab9aa5f13、不要针对 24-case 调参、Gate 3
  Holdout 保持冻结）。
