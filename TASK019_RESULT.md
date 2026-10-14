# Task019 结果

## 状态

Direct Hybrid 已在独立分支实现，Fake Runtime 端到端矩阵和离线回归通过。**真实 DeepSeek E2E 尚未启动**：Task018 的费用授权已结束，Task019 明确要求另行确认本轮额度。当前没有真实 Provider 请求，也没有 Task019 Live 结果可供正确率或费用比较。

## 版本与隔离

- 分支：`experiment/task019-direct-hybrid`
- 实现提交：`2bcc9a5c395ba67e771d563e32b4b232a6bb5ed9`
- B2 基线：`de0ca632c4a8a0b67d6f6bb1c2c6eb55d741d131`，业务 SHA-256 `2101868665a1c8f3732d66517b63bc1142a16968941368854be8ebd96201f028`
- Task019 业务 SHA-256：`9e216ddac3be326e13b8f3a1d2998a68344d4c99468e77a70f35912f7c26cce7`
- Task019 工作区已提交且干净。B2 和原 Task017 工作区未修改。

## Finalization 路径

- **A / `legacy`：** 原始 B2 的 `FinalAnswerAction → EngineeringEvidenceVerifier` 路径保持不变。真实产品入口默认仍为 `legacy`。
- **B / `direct_hybrid`：** 同一个 ToolAgent Decision 可以直接返回 `changed_files_finalization`，或普通 `final_answer`。Typed 结果立即交给现有 `finalize_changed_files_typed()` 校验并从 Observation 确定性渲染；它不会先经过旧 Gate，也没有旧 Gate 失败后的 Selector 兜底。Typed 结果不合法时会拒绝；Requirement 未满足时只能沿原有有界证据循环恢复，不能绕过 Requirement。
- 普通分析和 RAG 走普通回答路径：保留检索状态、旧 Requirement、当前 Run E-ID 校验，不运行旧自然语言 Binding 规则。该轻量检查不判断自然语言主张是否被引用来源语义蕴含，仍有错误解释风险。

实现涉及 `api/app.py`、`core/tool_agent/{actions,decision_prompt,runtime,runtime_models}.py`、`core/unified_engineering_runtime.py`、相关导出和离线测试。运行器侧复用了 Task018 的 Probe、共享预算闸门和 Live 入口，适配为本次 11 项计划及容错的字节输出解析；没有新增 Agent Loop、Selector 请求循环或通用框架。提交共 13 个文件、+2907/-19 行，其中大部分是复用并固定到本分支的 Task018 E2E 入口与 Fake Probe。

Agent 循环、Planner、Router、工具、5/4/2/60 预算未改。Direct Hybrid 的 Selector 内容由现有 Decision 请求直接产生；Fake 矩阵中没有额外 Selector 请求。相对 B2 的真实请求数、Token、延迟仍待 Live 测量。

## 离线结果

运行：

```text
python -m pytest tests\test_tool_agent_changed_files_typed_finalization.py tests\test_task018_e2e_preflight.py -q
45 passed, 2 warnings
```

警告是已有 Chroma/Jieba 弃用提示。Fake 调度经过真实 Runtime、隔离 Git/RAG fixture 和 Fake HTTP Transport：11 个计划运行、33 个 Fake Provider 响应，模型请求名为 `deepseek-flash`、Thinking disabled、temperature 0。该结果只证明接线和记录字段，不代表模型理解、答案质量或真实成功率。

在 Fake 脚本的固定响应下，四组 A 都被旧 Gate 拒绝，Direct Hybrid 四组都被 Typed 路径接受；三项 Direct 诊断按脚本分别完成 untracked、开放式重要性说明和 RAG 回答。这里的结果是预设 Fake 输出，**不计为 Agent 语义成功**。

Task018 已有真实记录 `task018-e2e-live-20261014-003` 可作历史参考：四组配对中原 B2 为 0/4、Task017 为 3/4。但该记录没有 Direct Hybrid。其 `case05/07/08` 只运行了 Task017，没有原始 B2 对照；这三项在本任务也只能作为 Direct 新架构诊断，不能伪称严格 A/B。Task018 的真实结果不能替代 Task019 Live。

## Live 计划与待批准额度

固定计划为 11 次 Agent 运行：全部变更、deleted、renamed、空工作区四题各跑 B2 与 Direct Hybrid，共 8 次；untracked、最重要变更、普通 RAG 再跑 Direct Hybrid，共 3 次。模型和预算为 `deepseek-flash`、Thinking disabled、temperature 0，最多 60 次请求、200,000 tokens、US$0.15 软件估算停止阈值、零自动重试。价格估算不是服务商账单保证。

预定 run_id 为 `task019-direct-hybrid-20261014-001`；对应结果目录目前不存在，未覆盖任何旧结果。复用入口会在每次 Live 前重新验证 B2/Task019 业务指纹、Prompt、fixture 和干净 Git 状态；只有显式传入 `--execute-live` 才能进入真实 Provider 路径。

启动命令：

```text
python -X utf8 evaluation/task018_e2e/live_e2e_runner.py --execute-live --run-id task019-direct-hybrid-20261014-001
```

## 判断

当前离线结果证明 Direct Hybrid 可以直接接入既有 Runtime，并移除 B2 的旧 Gate 阻断路径；它们不足以证明真实正确完成率改善。建议保留为隔离实验实现，暂不切换稳定默认。取得本轮费用授权并完成 11 项 Live 对比后，再决定是否替换旧 Finalization。
