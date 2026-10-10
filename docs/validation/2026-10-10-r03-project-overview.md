# R03：自然项目概览局部修复与验证

日期：2026-10-10。起点：`bdd9faf` 上未提交的 R01、R02 改动。结论：自然的当前项目概览请求已经能进入实际文档读取，而不是只回答绑定目录；局部验证通过。没有执行全盘评测、重启服务、提交或推送。

## 1. 复现与验收目标

原 SQLite 会话 `a632c53d96134a70a0f326f2d219396e` 中，“说一下目前的项目”曾被改写成上一轮目录问题，且 0 Tool Call 拒答。R01 修复请求交接，R02 增加绑定信息查询。本次先在 R02 完成状态下，用相同原句和相同六条历史进行对照：终态变成 completed，但模型只返回项目名、目录、绑定来源和可用状态，没有介绍用途，没有读取文档，也没有 project_doc Evidence。

因此本项验收不是“从 refused 变为 completed”，而是：保持用户本轮概览目标，查到当前绑定项目自己的介绍文档，实际读取正文，再依据该正文介绍用途、能力和已声明的边界。绑定元数据和文档路径都不能替代正文。

## 2. 修改边界

- `get_project_info_v2` 在不可变的服务端项目绑定上增加可选布尔参数 `include_documentation`。纯目录查询 `{}` 保留原四字段结果。概览查询只检查 13 个固定常用入口，最多返回 6 个安全的项目相对路径；包含根 README 的 md/rst/txt 与大小写变体，以及 docs/index、docs/README、docs/overview 的有限变体。
- 入口查询不递归列目录、不读取正文、不接收模型指定的目录或项目 ID。拒绝链接文件/中间目录、解析后越界路径和超过现有文件上限的候选。空结果只表示这组常用位置未找到可用候选，不等于项目完全没有文档。
- 复用现有 `read_project_context` file target 读取正文、产生 project_doc Evidence。没有新增导航工具、Evidence 类型或 Runtime 分支。
- Requirement Router v5 将“介绍当前绑定项目”接入已有 `PROJECT_DOC_V1`；源码、变更/测试、理论对照等更具体需求保持优先级。纯绑定查询、通用介绍方法和面试话术不被追加概览文档要求。v4 显式保留供兼容与对照。
- 新 Engineering Decision/Planner profile 指导上述流程。仓库概览不必检索知识库，但仍须满足项目文档要求。QueryPlan Schema、Parser、fallback、Evidence/Citation 终审保持原机制。
- API 工厂选择新 profile 和 v2 工具；旧工具和旧 profile 保留。Activity 只增加安全的入口数量/截断摘要，不将绝对根目录复制到活动摘要。

保持单一 Agent 循环和系统硬预算：5 次逻辑决策、4 次工具调用、2 次工具错误。Runtime、Executor、Guard、Verifier、数据库结构及 Reader 上限没有为此扩展。

## 3. 局部自动验证

最终代码的局部后端检查：**164 passed、1 skipped**（8.11 秒）。范围为 R03 新测试、项目文档要求、R02 绑定工具/项目隔离、R01 请求交接、Planner 对齐、既有 Router activation/rollback 接缝以及少量正式装配测试。不是完整测试集。

覆盖概览的中英文表达、绑定与介绍方法的排除、源码/变更优先级、真实文档读取和引用、仅入口/元数据不能完成任务、无 README 的 docs/index、空入口、同名项目 A → B → A、固定入口上限、路径越界、非法参数、长文截断和旧工厂/旧 profile 保留。

真实符号链接创建因本机 Windows 权限跳过。已另用注入链接状态的两个测试验证文件与中间目录的拒绝条件，并测试解析后越界；这些不能冒充本机真实链接集成测试。

前端已有局部检查 `node --test tests/frontend_stream_v2.test.mjs`：**13 passed**。`git diff --check` 通过。测试使用独立临时会话/项目数据库，不通过真实服务 lifespan 初始化生产数据。

## 4. 少量真实 DeepSeek 对照

模型：`deepseek-chat`，temperature=0。原始记录：[完整局部样本](2026-10-10-r03-project-overview-live.json)。每个场景只采样一次，保留拒答、解析修复及版本信息；这是一组开发/冒烟对照，不是独立统计评测。

| 样本 | 结果与内容 | 逻辑决策 / 工具 | 实际模型请求 |
|---|---|---|---|
| R02 基线：原问题 + 原六条历史 | completed，但只列绑定信息，0 项文档证据，未完成用途介绍 | 2 / 1 | 4 |
| R03：原问题 + 原六条历史 | completed；查询入口、读 README 1–120 行，介绍研发 Agent 定位/能力，引用 E1 | 3 / 2 | 5 |
| 新会话：用大白话介绍工程用途和现成能力 | completed；实际读 README，概括用途/能力，引用 E1 | 3 / 2 | 4 |
| 同名其他项目，无 README，有 docs/index.md | completed；正确介绍 JobQueue Desk 的图像转换队列、SQLite、worker 和只读仪表盘，未套用本仓库介绍 | 3 / 2 | 4 |
| 空项目，没有常用文档入口 | refused，`INSUFFICIENT_EVIDENCE_TO_FINALIZE`；无文档证据，没有编造用途 | 3 / 1 | 4 |
| 当前绑定目录原问题 | completed；空参数调用绑定查询，根目录匹配真实绑定，无额外文档读取 | 2 / 1 | 3 |
| 源码查询 ToolAgentBudget.max_tool_calls | completed；读取实际符号，回答默认值 4，引用源码 E6 | 2 / 1 | 4 |
| 最终工具描述校正后：原问题 + 原历史 | completed；仍查入口、读 README、介绍实际用途和能力，引用 E1 | 3 / 2 | 5 |

所有样本工具错误为 0，均在原逻辑预算内。源码回归的最终回答初次遇到 `ACTION_SCHEMA_INVALID`，触发现有一次 Action Parse Repair 并成功。因此该样本是 2 次逻辑决策、3 次 Decision 模型请求，加 Planner 共 4 次；不能以逻辑决策数代替实际成本，也不能声称没有模型协议错误。空入口样本经过现有 Guard 的一次纠正后停止，没有新增特殊终态。

累计 **33 次实际模型请求、134525 input tokens、3773 output tokens**，包含 R02 基线、六个 R03 场景和一次最终复验。

真实知识库为只读快照：revision 9，37 个文档、215 个 chunks，snapshot SHA256 `4f0b66f5bc2bb5a15d62eb327e4758bc9eddffcdc9e2a7bb4d4a92f380ea7fab`。原会话及 8 条消息前后逐项相同（`conversation_unchanged=true`）；本次测试没有向原会话追加答案。

## 5. 版本、边界与下一步

| 身份 | 当前值 |
|---|---|
| Decision | `engineering_agent_decision_prompt_project_overview_v7` |
| Decision SHA256 | `dc8838b484db443572178beeebfb9746a3cd0c40f20bf69786c4cc8481e7374c` |
| Planner | `engineering_planner_project_overview_prompt_v5` |
| Planner SHA256 | `96d15a63d472ee3f27ad6827ba8676686536416e79e6291c224e286118f36e37` |
| Requirement Router | `engineering_requirement_router_v5` |
| 绑定/入口工具 | `get_project_info_v2` |
| 最终 enabled Tool Set SHA256 | `bd1b5e9db4e4de64bb1328bb08cfa50924b5bf391b83994d3d541c6fadf8bd61` |

复查修正了一处 v2 工具描述继承 v1 的“参数必须为空对象”旧句的问题，仅校正文案作用范围，参数/执行逻辑未变。前七个真实样本的 Tool Set SHA 为 `0f1b217e50bc6b6aa4d5c570b45d2cf44f69f183855d4c23ecd5c42dd98eb64e`；最终复验记录新 SHA，保留前七个样本，不将它们改写成最终版本的测试。

限制：本项提供的是有实际来源的文档概览，不能证明源码实现、运行结果或部署状态。只覆盖固定常用入口；特殊文档布局仍可能需要用户提供路径。README 返回窗口实际被行数/行长限制截断，Evidence 和 Reader targets 保留 1–120 行、`content_complete=false`、`next_line=121`。前两个主项目样本主动说明读取范围，最终复验只说明文档来源和未核查源码，没有复述行号；模型对范围提示的表达仍不完全稳定，本次不增加新的终审规则来强制文案，也不宣称已经消除语义支持问题。

未修改 R04 的绑定入口展示、R05 的拒答提示或 R10 的历史详情问题；它们按计划分别收口。当前运行中的后端没有重启，需加载新工厂/profile 才会使用本项修改。改动未提交、未推送。
