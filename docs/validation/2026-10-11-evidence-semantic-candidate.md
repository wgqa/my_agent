# 需求分析与末端审核候选通路

日期：2026-10-11。状态：S1—S3 已实现并通过专项检查；保持默认规则路径，准备已知题真实开发对比。正式新题验收未开始。

## 本次实现

- 复用 requirement provider 和需求 v2 合同。保留 v1 prompt，候选 v2 prompt 接收实际启用工具及 schema；没有有效合同则明确 failed，不回退或当作闲聊。
- 从实际成功 Observation 登记正文、知识、定位、列表、测试候选、计算和绑定事实。来源包含调用 ID、工具/schema 版本、绑定身份、返回内容 hash、范围和完整性；失败不伪装成成功空列表，不跨快照拼接签发完整函数。
- 原 Runtime 中增加候选策略分支，沿用一个循环和 5/4/2 上限。逐轮只更新程序进度；只在候选答案/拒答时语义审核，最多两次，无隐藏 JSON 修复或 SDK 重试。
- 补材料、改答案与过早拒答复核均由原执行 Agent 继续，额度不重置。没有工具额度仍可改已有材料的答案，最多一次提交修正。资料和审核记录均为每次运行独有。
- 程序阻止未知引用、错误对象、已知截断、过期批准等可核对问题。审核服务故障为 failed，真实证据不足/恢复额度耗尽为 refused，非完成状态始终没有答案。
- CandidateToolAgentRunResult、公开 engineering_query_response_v2 独立于旧类型。新增 tool_result 采用实际工具的闭合 schema，没有伪造行号。API、V2 活动流与 HTML 来源卡同步支持；旧规则、旧 verifier、旧提示词和 SSE V1 保留。

## 配置和使用

服务端三项配置在装配时冻结，不接受前端提交模式、模型、权限或预算：

| 组 | ENGINEERING_REQUIREMENT_MODE | ENGINEERING_EVIDENCE_POLICY | ENGINEERING_FINALIZATION_POLICY |
|---|---|---|---|
| A / 产品默认 | rule | legacy | legacy |
| 影子比较 | shadow | legacy | legacy |
| B / 实验 | rule | goal_v2 | structural_v2 |
| C / 实验 | llm | goal_v2 | structural_v2 |
| D / 候选 | llm | goal_v2 | semantic_v1 |

B/C 是归因对照，不能宣传成已做语义验收。D 也需独立评测，不能把 reviewer 的 accept 当作 Gold。没有修改本机 .env，没有重启 8000 服务。

## 已执行验证

1. S1：材料与活动/证据专项 27 项通过，前端 31 项通过。
2. S2/S3：多对象补查、零工具闲聊、过早拒答、引用修正、截断、未知 ID、审查故障、合同漏项、取消、并发隔离、公开来源和 SSE 发布规则等专项通过。
3. 72 模块联合离线回归：1494 通过、10 跳过；唯一失败为旧 OpenAPI 测试只认单一旧响应。接口已明确声明新旧响应联合，该测试改为同时检查两份类型。记录：data/runtime/requirement_offline_j0vwqjgi/。
4. 修正后针对 OpenAPI 和所有候选新模块复验：52 通过、74 未选中。记录：data/runtime/requirement_offline_rtu7n4i8/。两次均未连接外网/8000，业务源文件运行期间没有变化。
5. 审核输出和需求 prompt 的补充检查，以及候选 Runtime/API、开发对比入口联合验证：179 通过。记录：data/runtime/requirement_offline_zkcqyd9q/。审核 accept 允许空反馈；合同覆盖原问题与答案尚未完成分别判定。
6. 冻结 f4c9317 后完整 73 模块回归：1498 通过、10 跳过、0 失败；前端 31 通过。记录：data/runtime/requirement_offline_skkh448h/。无外网/8000 连接、无代码漂移。

上述固定模型测试验证通路和边界，不是模型质量通过率。最终整体检查及真实开发结果在下方追加，保留首次失败与后续修正记录。

## 真实开发评测入口

运行 evaluation.tool_calls_v2.evidence_experiment。默认只选择冻结的 12 道已知开发题，A/C/D 各一次，共 36 次；缺省不调用模型，只准备独立 fixture 和知识副本，显式 --live 才调用真实模型。

产物在新建 data/runtime/evidence_experiments/<run_id>/，包括业务/评测/项目/知识身份、逐题原始运行和材料/审核记录、阶段实际用量及独立工具材料分数。保留原始结果，文件变化即中止；不向当前服务或真实数据库发请求，不将 Gold 输入模型。

准备检查已生成 semantic_prepare_20261011：36 次计划运行、0 次模型调用，项目 fixture 与冻结协议一致。每次真实运行另外记录实际 Decision、需求和审核 prompt 的版本/hash、模型、工具 schema、输出上限及重试/超时设置。

答案质量需要单独对原问题、独立 Gold 和实际工具内容复核，不能从工具分数或 reviewer 批准推导端到端通过率。正式 72+24 新题四组验收仍依赖本轮开发对比结果。

## 首次开发对比及修正

semantic_pilot_20261011_v1 固定 f4c9317，36 次任务全部保留。A/C/D 完成数分别为 8/5/6，D 另有一次 REVIEW_OUTPUT_INVALID。原评分器不认识新增阶段记录，36 次原始工具分数为 INVALID；这是评测适配缺口，不能当作系统零通过率。

补充 engineering_tool_record_projection_v1：先核对新阶段 schema 与实际 SDK 调用数，再将需求/审核阶段单独留存，将完整工具、Decision、终止记录交给未修改的旧工具评分器。原序号映射、输入 hash、源文件 hash 和原始分数均保留；Gold 和旧 scorer 未变。首次原记录离线重评分、零模型调用，严格工具路径 PASS 为 A 8/12、C 5/12、D 5/12；文件为原运行目录的 tool_scores_projected_v1.json。

源码复核发现候选材料目录包含新类型，但可信旧引用目录排除了 tool_result，存在两份目录冲突。新候选 Decision v9 仅保留系统预算控制，完整引用从当前 material_catalog 读取；v8 和旧产品 v7 均保留。引用修正反馈列出实际目标编号，不放宽未知编号/对象/截断检查。另将每次实际答案或拒答（含审核前被程序拦截的提交）记录为内部 audit_v2，保留材料/提交 hash 和判定；不会进入公开答案或 SSE。

上述修正与评分适配联合专项：209 通过，记录 data/runtime/requirement_offline_wt3_6jkf/。需要新冻结版本再做同范围开发对比，首次数据保留，不能择优替换历史结果。

第二次 semantic_pilot_20261011_v2 冻结 6c34044，36 次全部运行。A/C/D 严格工具路径 PASS 为 8/3/4，D 另有一次 REVIEW_OUTPUT_INVALID；未出现改善。73 模块回归 1503 通过、10 跳过、0 失败（requirement_offline_wp2a14yy）。完整提交记录揭示主要失败：答案写成“依据 E6”或“（E6）”，而程序只解析 `[E6]`，反馈又只给裸编号。因此资料充分、编号正确，仍会被判为缺引用。这不能归因为需求模型不理解任务，更不能用已通过的固定输出测试代替真实质量。

进一步修正：候选 Decision v10 明确机器引用语法，修正反馈使用实际 `[E#]`；保持严格解析与有限次数，不把普通变量名当引用。ledger_v2 单独记录真实工具尝试的状态/错误，不分配 E-ID，不把错误当正文或成功空结果；审核 prompt_v2 接收这些实际诊断，判断是否合理拒答。被审核确认的实际 RefuseAction 保留原原因码。审核非法输出增加闭合诊断类别，仅存程序校验类别，不保存原始模型输出或隐藏推理。

新增回归覆盖“先有知识 E1、后有计算 E2、格式错误后修正”以及“文件读取真实失败、审查可见失败、确认拒答原因不被改写”。本次八模块专项 220 通过（requirement_offline_oodsjwwr）。新冻结版本仍需相同范围开发对比；此前两次完整保留。
