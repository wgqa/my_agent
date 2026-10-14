# Task019：Direct Hybrid 真实 E2E 结果

## 结论

授权的 11 次运行全部完成。四道配对任务中，B2 原 Finalization 的实际交付为 0/4；Direct Hybrid 为 4/4，且答案与隔离 Git fixture 一致。Direct Hybrid 的三个诊断任务中，untracked 与普通 RAG 正确完成；“最重要变更”生成了谨慎的证据不足说明，但未通过现有子查询覆盖检查，最终没有交付。因此本轮 Direct Hybrid 为 6/7 个任务正确完成。

建议保留 Direct Hybrid 作为隔离候选实现，暂不切换稳定默认。四组配对显示它确实绕过了旧 Binding 对可信 changed_files 事实的错误拒绝；样本只有四组，且开放式问题仍被旧 Requirement 覆盖检查挡住，尚不足以证明整体架构已可替换。

## 身份与运行记录

- 实验分支：experiment/task019-direct-hybrid
- 实际运行代码 HEAD：8cd3d1de8818cf2a722097f65945d028bf07619e
- Task019 业务指纹：9e216ddac3be326e13b8f3a1d2998a68344d4c99468e77a70f35912f7c26cce7
- 对照 B2：de0ca632c4a8a0b67d6f6bb1c2c6eb55d741d131，业务指纹 2101868665a1c8f3732d66517b63bc1142a16968941368854be8ebd96201f028
- run_id：task019-direct-hybrid-20261014-001
- 结果目录：D:\学习\rag实战项目\_task019_direct_hybrid_live_results\task019-direct-hybrid-20261014-001
- Manifest 授权标记为 PROJECT_OWNER_AUTHORIZED_TASK_019_LIVE；冻结 Prompt、fixture 和源码身份见该目录 manifest.json。
- 原始运行产物的 sha256sums.json 中 7 个文件均逐项复算匹配。运行结束时 11/11 已执行、0 失败、0 未执行；没有覆盖旧运行记录。
- B0、Candidate、冻结 B2 与 Task017 工作区未被本次实验修改。当前 Task019 工作区在本报告提交前仅有本报告变更。

真实请求使用 DeepSeek deepseek-flash、Thinking disabled、temperature 0、SDK retries=0。请求与响应模型 32/32 一致；32 次均有 usage，账单状态已知。日志没有保存 API Key 或凭据 Header。

## 实际执行路径

- B2：Planner、ToolAgent Decision 与 changed_files Observation 后生成普通 FinalAnswer，再经过 EngineeringEvidenceVerifier。四道配对题都因 ANSWER_EVIDENCE_REFERENCE_INCOMPLETE 拒绝交付。
- Direct Hybrid：共享 Planner、Agent 工具循环、Router、Git/RAG 工具与原预算；FinalAnswerAction 可直接选择 Typed changed_files Action 或普通回答。Typed Action 直接由来源 Observation 校验并渲染，不先走旧 Gate，也没有第二次 Selector 请求。普通回答走新的轻量来源检查。
- 四道 Direct 配对题均由真实 Agent 调用 changed_files 取得 Observation；不是注入预制 Observation。case01、case02、case04 使用 Typed Finalization；case03 的模型直接给出普通答案并由轻量检查接受。

## 逐题结果

| 案例 | B2 | Direct Hybrid | 按冻结 fixture 核对 |
| --- | --- | --- | --- |
| case01：commit range 全部变更 | FinalAnswer 被旧 Gate 拒绝 | Typed list_all 完成 | 正确交付 5 项；包含 added、modified、deleted 与 old/new rename 路径 |
| case02：只列 deleted | FinalAnswer 被旧 Gate 拒绝 | Typed filter_status=deleted 完成 | 只交付 src/retired_source.py，正确 |
| case03：rename 旧、新路径 | FinalAnswer 被旧 Gate 拒绝 | 普通 FinalAnswer 完成 | 正确交付 src/old_parser.py → src/new_parser.py；附带的完整清单也与 Observation 一致 |
| case04：检查干净 working_tree | FinalAnswer 被旧 Gate 拒绝 | Typed list_all 完成 | 明确说明检查范围、清单完整且为空、未发现可见变更，正确 |
| case05：列出 untracked | 未运行 B2 | Typed list_all 完成 | 正确交付唯一条目 notes/local_sample.md |
| case07：哪些变更最重要 | 未运行 B2 | 未交付，拒答 | 模型说明仅凭状态清单无法排序，并提出需要读取 diff；但 Planner 将影响面和重要性依据拆成必需子查询，Agent 只调用 changed_files、没有读取 diff，最终因 INCOMPLETE_SUBQUERY_COVERAGE 被拒绝 |
| case08：普通 RAG 问答 | 未运行 B2 | 普通回答完成 | 回答标准重试窗口为 12 秒，并引用本地知识 Evidence E1，正确 |

case07 的实际候选回答是合理的证据边界说明，但 Gate 结果为 refused，用户没有收到它；故不计为完整成功。它暴露的是 Planner/Requirement 子查询覆盖与“可以明确说明证据不足”之间的冲突。本轮未改 Prompt、Router 或 Gate，也未重跑。

## 成功率与调用开销

| 范围 | 运行数 | Provider 请求 | Tokens（输入/输出/总计） | 软件估算费用 | Provider 延迟合计 | Runtime 执行耗时合计 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| B2 配对四题 | 4 | 12 | 47,553 / 1,031 / 48,584 | US$0.0155031 | 11,032.6 ms | 12,123 ms |
| Direct 配对四题 | 4 | 12 | 51,644 / 666 / 52,310 | US$0.0162924 | 10,946.0 ms | 12,026 ms |
| Direct 全部七题 | 7 | 20 | 84,113 / 1,330 / 85,443 | US$0.0268299 | 20,993.1 ms | 22,729 ms |
| 本次总计 | 11 | 32 | 131,666 / 2,361 / 134,027 | US$0.042333 | 32,025.7 ms | 34,852 ms |

配对 Direct 比 B2 多 3,726 Tokens（约 7.7%），估算费用多 US$0.0007893（约 5.1%）。配对 Provider 延迟合计少 86.6 ms，Runtime 执行耗时合计少 97 ms；四组样本不足以据此声称速度提升。

配对两组都是每题 3 次请求（1 Planner、2 Decision），没有观察到相对 B2 的请求数减少。Direct 的 12 次配对请求中没有独立 Selector 角色或修复重试；因此它避免了额外 Selector 路径，但本次对照不能宣称比 B2 少调用。全部 32 次调用由 11 次 Planner 与 21 次 Decision 构成。

预算上限为 60 请求、200,000 Tokens、US$0.15；实际分别为 32、134,027、US$0.042333。未触发停止阈值，没有自动重试或未决账单状态。美元数是冻结价格下的软件估算，不是服务商账单保证。

## 判断与边界

- 配对四题的 Direct Hybrid 交付事实均符合 Git fixture；B2 的四份候选答案也列出了正确事实，但全部被旧 Binding Gate 拦截。
- 没有观察到错误的 Typed 过滤、rename 方向颠倒、空清单误报或普通 RAG 路径损坏。
- case07 是明确失败：Agent 未取到 diff，且正确的“不足以判断”候选答案也未交付。后续若处理，应单独决定是否调整开放式任务的覆盖策略；不能把本次拒答算作答案正确。
- 这是四组配对加三项单组诊断，不是大样本成功率评估；语义核对由本次执行者按冻结 fixture 完成，不是独立盲审。
- 建议保留 Direct Hybrid 候选并进行代码评审；暂不改稳定默认。下一步应优先审查 case07 的覆盖拒绝是否符合产品意图，再决定是否做更大规模消融。本轮没有继续修改实现或发出额外 Provider 请求。
