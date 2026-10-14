# Task020：Hybrid Task Contract 开发结果

Task019 已推送到 origin/experiment/task019-direct-hybrid，远端 HEAD 为 4658857ce7a4b61dce0bdcea98f72cb9a3e5c0d2，包含 2bcc9a5c 实现和最终真实实验报告。原始实验记录在仓库外，未上传密钥、环境文件、数据库或大型日志。

Task020 基于该 HEAD，在独立工作区 D:\学习\rag实战项目\rag-knowledge-base-hybrid-task-contract、分支 feature/hybrid-task-contract 完成。没有真实 Provider 请求。

## 实际能力

- 复用同一次 Knowledge Planner 请求，增加轻量任务契约：操作、文件/函数等对象、明确路径/符号、Git 范围、状态及正文/diff/完整清单/测试执行/知识材料要求。没有新增 Planner、Reviewer、Ledger 或 Agent Loop。
- 新模式 hybrid_task_contract 用契约投影最终材料要求，复用原 Evidence Requirement evaluator。旧 Router 保留作 legacy/direct_hybrid 对照和未知任务的兼容下限；受支持的明确任务不再由旧 Router 分类裁决。
- “列出已删除的源码文件”由经过来源验证的 changed_files 状态事实支持，程序按现有项目文件分类筛选源码，保留状态、rename 方向及 Scope。不会因“源码文件”三个字额外要求读取正文。
- 源码解释需要所需路径的真实正文；具名函数还需完整定义或可验证的完整文件。复用 Reader 元数据和现有 Python 符号索引。Locator、错误路径、未引用正文、截断定义不能替代这些材料。
- 执行测试是单独的真实执行义务。现有 Registry 没有测试执行工具，因此 find_tests 候选或测试源码不能被宣布为已执行、已通过。
- Typed 选择必须对应任务对象、状态和 Git Scope。用户要求完整清单时拒绝截断/敏感遗漏来源；明确的有限结果可带限制交付。完整变更分析需要完整状态范围及其 diff，单文件 diff 不能证明全范围。
- 普通分析与 RAG 继续使用原 Agent 的自然语言 FinalAnswer；新模式校验被引用的当前来源及材料要求，不重新加入旧自然语言格式 Binding。

产品装配支持系统配置 ENGINEERING_FINALIZATION_STRATEGY=hybrid_task_contract；默认仍为 legacy，也可以显式选 direct_hybrid。当前服务没有重启或切换。

## 调用与代码范围

链路为 Context → 现有 Planner（同次输出 Task Contract）→ 现有 Retrieval → 同一个 ToolAgentRuntime → ToolObservation/Evidence → Direct Hybrid Finalization。

没有额外 Selector/契约模型请求；Planner 的 temperature、800 输出上限、超时与重试策略保持原样，Agent 仍为 5 Decision / 4 Tool Call / 2 Tool Errors / 60 秒。新 Prompt 和契约输出会增加一定 Token；本轮没有真实测量增量。

核心改动为 core/engineering_task_contract.py（307 行）及 Planner、Unified Runtime、Verifier、Typed Finalization 的必要接缝；另有两个专项测试文件。相对 Task019：14 文件，+1063/-32 行，其中 523 行是新增测试。Git 工具和正式评测器没有修改。

小步提交：

- dce330411dd5a48e2d971f9b2035b19930c739a9：同一次 Planner 调用提取契约，保留旧协议。
- b9e65d822d9ee45709d340048c5a6cfe1a3fee97：接入任务、来源及 Scope 约束。
- 31dbae5d7348d3a7ca8d7e31db65e9e31c8b5689：真实 Runtime/Fake SDK 回归。

## case07 的两个独立问题

原记录 task019-direct-hybrid-20261014-001 中，Planner 将变更内容、影响面、重要性依据拆成三个必需知识子查询。EngineeringEvidenceVerifier 将 MinimalEvidenceVerifier 的 INCOMPLETE_SUBQUERY_EVIDENCE 映射为 INCOMPLETE_SUBQUERY_COVERAGE；该覆盖检查依赖固定 Knowledge Retrieval Snapshot，Git 工具结果不会补齐其 query_id。

同一记录里 Agent 只调用 changed_files，没有 git_diff。前者是额外知识覆盖门槛，后者是真实变更材料缺口，不能混为一个原因。

新模式让无需知识库的仓库任务不再受知识子查询覆盖门槛裁决，但真实 diff 义务仍保留。离线回归证明：没有 diff 继续拒绝；完整范围分析只取得单文件 diff 也继续拒绝。没有重做工具规划器，也没有宣称历史 case07 已变成真实成功。

## 离线结果

- 新增 47 项契约及真实 Runtime 接缝测试全部通过。Fake SDK 由真实 Provider parser 消费，Agent 自己创建 ToolCall；Git 查询和 Reader 访问原 Task018 隔离 fixture。
- 相关 Planner/Requirement/Verifier/Runtime/Context/API 回归：403 PASS、3 FAIL、0 SKIP。三项失败在原 Task019 HEAD 逐项复现，均是旧 API 断言期待 B2 适配前的 Evidence 数量/编号：
  - test_repository_only_returns_project_code_evidence
  - test_cross_source_combines_knowledge_and_repository_evidence
  - test_change_test_vertical_returns_both_project_evidence
- 原 Fake E2E/预算接线回归：19 PASS；1 项固定 Task019 Live 身份检查未选择执行，因为它应继续校验冻结 Task019，而不能把 Task020 的变化视为同一冻结业务版本。原测试和冻结身份没有改写。
- 警告为既有 Chroma、Jieba、Starlette 弃用提示。测试目录和数据库均使用独立临时目录；真实 Provider 请求为 0。

观察到的结构反例全部阻断：误选状态、错误 E-ID、跨 Git Scope、越界 Reader、完整清单截断、locator 冒充实现、借用未引用正文、错误函数范围、候选测试冒充执行、单文件 diff 冒充完整范围。

这些结果证明接线与确定性材料约束，不证明真实模型的契约理解或最终语义成功率。自然语言分析仍没有通用语义蕴含审核；模型误解隐含需求、引用真实来源却作错误解释，仍是风险。未知复合任务保留兼容下限，可能发生保守拒答。

## 后续判断

建议保留这次实现，下一步最需要处理的是 Agent 按契约补齐真实 diff，而不是只拿到状态清单后提前结束。广域分析可能因原 4 次工具预算无法取得全部材料而拒绝；本轮没有扩大预算。

如批准真实验证，建议仅用四题：删除源码路径、src/main.py 的 scale 函数解释、变更重要性、普通知识问答。使用 Flash、Thinking disabled、temperature 0；最多 4 次 Agent 运行、32 次 Provider 请求、120,000 Tokens、US$0.10 软件费用停止阈值、SDK retries=0。该额度尚未获本轮执行授权，软件阈值不是账单保证。

Task020 到此停止，不启动真实模型或扩大实验范围。
