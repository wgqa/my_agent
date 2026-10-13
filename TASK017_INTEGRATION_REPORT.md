# Task 017：Typed Finalization 最小集成报告

## 身份与工作区

- 基线：B2 `de0ca632c4a8a0b67d6f6bb1c2c6eb55d741d131`；任务卡给定基线业务指纹 `2101868665a1c8f3732d66517b63bc1142a16968941368854be8ebd96201f028`。
- 隔离工作区：`D:\学习\rag实战项目\rag-knowledge-base-typed-finalization`。
- 分支：`feature/typed-finalization-integration`，由指定基线创建。
- 实现提交：`8f48ed0e7cf90e6c2f3d707fecf261fdd4fa86ff`。
- 实现提交后工作区干净。Task 017 没有改动主 Candidate 工作区、B0、冻结 B2 或 Task 016 工作区；它们仍保留为独立 worktree。
- 本轮没有调用 DeepSeek 或其他真实 Provider，也没有读取、写入或更改密钥。

## 原有执行链与接入点

```text
api/app.py 装配
  → UnifiedEngineeringRuntime.run
  → Context / Planner / Rule Requirement / Retrieval
  → ToolAgentRuntime.run 的 Decision / Tool / Observation 有界循环
  → ToolObservation 经 _evidence_from_observation 生成公开 Evidence 和 E-ID
  → FinalAnswerAction
  → 原 EngineeringEvidenceVerifier
  → 原答案交付或原恢复/拒答
```

主要位置：`api/app.py:178-181` 装配 Unified Runtime 和 Verifier；`core/unified_engineering_runtime.py:133` 进入统一运行时；`core/tool_agent/runtime.py:826` 是既有 Agent Runtime 入口，`:1112` 处理 FinalAnswer，`:364` 的 `_evidence_from_changed_files` 将成功的 `changed_files` Observation 保持为 `status_list` Evidence，`:687` 调原 Verifier。

Task 017 没有新增 Runtime 或 Agent Loop。Typed 分支仅挂在同一个 `FinalAnswerAction` 接缝上：先执行旧 Gate；只有旧 Gate 未通过、检索与旧 Requirement 已满足、拒绝原因仅为 Citation/Binding 类，并且当前运行恰有一份成功且可核验的 `changed_files` Evidence 时，才调用可选 Selector。旧 Gate 本来通过时不会因为 Agent 曾调用 `changed_files` 而强制转换成 Typed 输出。

## Typed 路径

- 冻结 B2 基线未包含 Task 016 的实验模块；Task 016 版本位于 `evaluation/tool_calls_v2/changed_files_answer_protocol.py` 和 `evaluation/tool_calls_v2/changed_files_typed_finalization.py`。为避免生产 Core 依赖评测层，本次没有合并 Task 016 Runner，而是在 `core/tool_agent/changed_files_typed_finalization.py` 按其已验证的有限 Selector / Typed Finalization 规则做了生产接缝适配。
- 新模块只接受 `list_all`、五种状态的 `filter_status`，或两种显式拒绝；不接受模型提供的文件行、状态、重命名路径或范围。
- Selector 输入由真实用户请求、原 Router Requirement、当前实际 ToolCall、成功 ToolObservation 和对应 Evidence 构成；Gold 不进入请求。
- `core/tool_agent/openai_compatible.py:399` 复用当前 Provider client 和模型，发出一个受限 JSON 请求：temperature 0、最多 128 输出 tokens、现有 20 秒 timeout、SDK `max_retries=0`。每个 Agent run 最多触发一次 Selector 请求，不做解析修复、不重试、不调用工具。它在 5 Decision/4 Tool Call/2 Tool Error 主循环之外，作为额外的单次 Provider 请求计量，不能误报成原决策预算内的调用。
- `core/tool_agent/runtime.py:717` 限制触发原因；`:1112` 负责同一最终回答接缝中的调度。Selector 的实际调用数、延迟和 usage 被加入执行指标并传递到 API；Provider 请求失败/解析失败按失败结束，错误 E-ID、来源或 scope 按拒答封闭。显式 `unsupported_request` 不产生 Typed 答案，继续原自然语言答复的恢复/拒答流程；如果原 Gate 未通过，仍由旧机制决定恢复或拒答。`insufficient_source` 拒答。
- `finalize_changed_files_typed()` 重验当前 Evidence 集中的唯一 E-ID、工具名、Observation 成功状态、ToolCall/Observation call_id、工具版本、参数和重新计算的 B2 Evidence 投影。随后仅把所选的 `status_list` Evidence 交给现有绑定 Verifier 做 Retrieval / Requirement 检查；不会把新渲染 Markdown 再送进旧 Citation Binding，也不会借用无关 source_body/diff 满足 Requirement。
- 程序从可信 Evidence 渲染路径、状态、rename old/new 方向和工具 scope。完整空清单明确表示范围检查成功、结果完整且没有可见变更；部分/截断结果标明返回数量和“不穷举”。失败工具不生成可信空清单。

## Requirement、开放任务与限制

- Router v5、Planner、Decision Prompt、工具 Schema/执行、`ToolAgentRuntime` 主循环及 5/4/2/60 预算没有修改。`dev-015` 的“已删除源码文件”仍由 Router 归类为 `PROJECT_CODE_V1`，status_list 不能替代源码正文；离线测试确认 Selector 没有被调用，旧 Requirement 仍阻断。
- 对重要性、原因、风险、Bug 可能性、模块影响等开放问题，如果旧 Gate 未通过而进入 Selector，Selector 提示会要求返回 `unsupported_request`，随后继续原自然语言回答的恢复/拒答流程。旧 Gate 已通过时不会调用 Selector。若原 Gate 本身拒答，本次不修旧链路。
- 对“全部”请求，模型若错误选择一个语法合法的窄状态过滤，程序会只渲染该状态并清楚标注范围；这是来源可信的 Typed 输出，不是已验证的任务完成。`TypedFinalizationResult.user_task_coverage` 明确保持 `UNASSESSED_NO_SEMANTIC_REVIEW`，但此诊断字段目前不随公开 API 结果返回。系统没有独立语义 Reviewer，离线 Fake Selector 不能证明真实模型理解了请求。Runtime 的 `completed` 表示答案已通过协议、来源和旧硬约束并交付，不等同于 Gold 语义 PASS；真实任务覆盖必须在后续实验中单独核对。

## 改动范围

实现提交共 10 个文件：新增 Typed 适配模块和 Runtime 集成测试；修改 Runtime 调度、Provider 接口、执行用量指标、Unified Runtime/API 指标字段、前端用量展示，以及一条既有 API 指标断言。变更统计：**1,370 insertions / 9 deletions**。没有引入 Task 016 Runner、Gold Sidecar、历史结果、Gold、Scorer、Prompt Router 或生产 Requirement 改动。

仓库没有 `package.json` 或前端测试脚本；前端文件完成 Node 语法检查。

## 离线验证

- Task 017 Runtime 集成专项：**21 passed**，2 条依赖告警。
- 相关 Runtime、Verifier、B2 Evidence、Provider、Unified Runtime 和 API 回归：**133 passed，3 deselected，0 failed**，3 条依赖/框架弃用告警。
- 排除的 3 项为旧 API Evidence shape 断言：`test_repository_only_returns_project_code_evidence`、`test_cross_source_combines_knowledge_and_repository_evidence`、`test_change_test_vertical_returns_both_project_evidence`。它们在精确基线 `de0ca...` 上也有相同失败，属于 B2 ToolResultEvidence 接口变化后未更新的旧断言，不是 Task 017 新回归；本轮未改这些断言。
- 专项覆盖完整清单、deleted/modified/renamed/untracked、commit_range、完整空结果、空筛选、截断部分结果、合法但过窄的 Selector、错误 E-ID、来源/范围篡改、工具失败、`dev-015` Router 阻断、开放分析走旧 Gate、普通 RAG 不触发 Selector、畸形 JSON/refusal 和 Provider Fake 单请求参数。
- `compileall`、`node --check frontend/js/app.js`、`git diff --check` 均通过。
- Fake Provider 的 Selector 结果是离线夹具，只证明 Runtime 接线、协议解析和确定性事实渲染；不证明模型决策质量或最终用户语义正确。

## 结论与后续条件

离线 Runtime 接缝已打通，来源及旧 Requirement 检查保留，B2 文件清单的格式型错误拒答具备进入小样本真实 Agent 验收的技术条件。下一步仍需项目所有者单独批准真实 Provider 调用与预算，并在实验中保留 Selector 的额外调用、Token 和延迟。应特别观察模型是否选对 `list_all` / `filter_status`、`dev-015` 是否仍被 Router 阻断，以及开放任务是否仍沿旧路径处理。

本结论分层如下：

- **单元/组件测试：** 通过。
- **真实 Runtime 接缝（Mock Provider）：** 通过。
- **用户任务语义正确：** 未由本轮确认；Fake 选择不能计作语义成功。
- **真实模型端到端效果：** 未验证；本轮没有真实 Provider 请求。
