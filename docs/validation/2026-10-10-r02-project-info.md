# R02：当前会话绑定目录查询

日期：2026-10-10。基线：`bdd9faf` 加已完成的 R01 工作区改动。本次只处理绑定信息的聊天入口，未提交、未推送。

## 结论

原问题“目前咱们的系统绑定的哪个项目目录”在 R01 链路仍然第一次决策直接拒答，0 次工具调用；R02 通过本轮 `get_project_info` 查询真实绑定后完成，2 次决策 / 1 次工具调用，准确返回 `D:\学习\rag实战项目\rag-knowledge-base`。另一种目录问法及另一处同名项目也完成，源码读取控制仍取得真实源码并引用 `[E6][E7]`。

这是五个开发回归/冒烟样例的实测结果，不是独立评测集或所有自然表达的成功率。没有修改、补写或重放进真实聊天数据库。

## 根因与实现

会话项目已由服务端选定并绑定到该项目的 facade / 文件工具；原聊天工具面没有获取项目绑定记录的能力。改写正确也不能让模型凭空知道本机绝对目录。此前 Planner 还会为这个平台事实查询检索知识库，得到与绑定事实无关的五条 Knowledge Evidence，但它们不能回答本机当前目录。

新增 `get_project_info_v1`，参数严格为空对象，返回 `project_name / root / source / available`。`ProjectBinding` 是服务端构造的不可变身份，registry 验证其根目录与既有文件工具一致。不能由模型或历史传入项目 ID / 路径，也不列出其他项目、不扫描文件。目录可用性在调用时检查，不回退其他目录。

Engineering 产品装配显式启用工具。默认旧装配仍注册七工具；Engineering 加入后注册八工具，进入统一执行时仍禁用动态 `knowledge_search`，因此本轮模型可见工具由六个增加到七个。

Planner v4 为纯绑定事实使用现有 `no_retrieval` 组合；Decision v6 要求取得本轮绑定结果再回答。R01 的当前任务/历史指代规则保留。平台状态不产生新的 Evidence kind，不伪造 `[E#]`，也不能满足源码、文档、测试或变更取证要求。Activity 只保留目录是否可用，并展示“查询项目绑定”，不复制绝对根目录到通用活动摘要。

核心循环、5 次逻辑决策 / 4 次工具调用 / 2 次工具错误、Executor、Parser、最终校验、Requirement Router 和数据库表结构未因 R02 改变。新增能力走现有 Tool 注册和执行扩展点。

## 局部离线验证

99 项后端局部检查通过，范围仅为 R02、新旧项目绑定、Planner 装配、R01 交接、活动摘要及四个历史 profile 装配检查；没有跑全盘测试。另有现存前端流式/活动模块的 13 项 Node 检查通过。

主要覆盖：

- Parser、Executor 分别拒绝 `root / path / project_id` 参数，工具权限和调用预算仍生效。
- 中文及空格目录完整返回；删除测试目录后查询返回原绑定及 `available=false`，不猜测其他目录。
- 同名项目 A→B→A 的两个真实消息 SSE 版本均查询正确项目；每轮结果保存到自己的消息。并发执行时绑定互不影响。
- 用户或历史声称其他目录不能改变实际绑定；共享 facade 不存储可变的“当前会话”。
- 仅得到平台元数据却尝试回答明确的源码、README、测试或变更任务，现有校验仍拒答。
- 默认项目直接查询入口正常；公共 `/project` 与项目列表保持原有字段契约，不因新工具批量公开本机目录。
- 原有失效目录的消息请求继续返回 409，历史仍可查；此次没有改写该 API 可用性策略。
- 新 profile 保留原 1200 输出 token 上限及单次 Action Parse Repair；旧工具集合/profile 可用于对照。

新增测试最初有结果属性名、预算属性名和可选活动字段的断言错误，已修正为真实接口；三条正文取证测试改用现有 Router 已支持的明确取证表达。此次没有为这些表达差异扩大词法规则，也没有把平台元数据作为正文证据。

## 真实 DeepSeek 对照

模型 `deepseek-chat`，temperature=0。上下文 Resolver、Planner 和 Decision 均实际调用；取证使用真实 Reader，Knowledge 使用只读快照构建的内存 BM25。原会话仅以 SQLite `mode=ro` 读取，执行结果只写验证文件。原问题对照两侧使用同一份四条历史消息和同一原句。

知识快照：revision=9，37 文档 / 215 chunks；SHA-256：`4f0b66f5bc2bb5a15d62eb327e4758bc9eddffcdc9e2a7bb4d4a92f380ea7fab`。

| 样例 | Planner | 终态 | 决策 / 工具 | 实际结果 |
|---|---|---|---|---|
| R01 原目录问题（对照） | single_retrieval | refused | 1 / 0 | INSUFFICIENT_INFORMATION；五条 Knowledge 不提供绑定事实 |
| R02 同原句、同历史 | no_retrieval | completed | 2 / 1 | get_project_info；真实工程根目录，无虚假 Evidence |
| “当前会话挂载的是哪个本地目录？请给出完整路径。” | no_retrieval | completed | 2 / 1 | 正确工程根目录 |
| 另一处同名 my_agent（中文、空格路径） | no_retrieval | completed | 2 / 1 | 返回该临时绑定自己的根目录和 configured 来源 |
| 查询源码 max_tool_calls 默认值 | single_retrieval | completed | 2 / 1 | read_project_context 读取字段及校验函数；默认 4，引用实际 E6/E7 |

五条记录全部保留，没有用多次重试筛掉失败。本次共 16 次物理模型调用，52,718 input / 796 output tokens。纯目录查询有历史时为 1 次 Resolver + 1 次 Planner + 2 次 Decision；无历史时为 1 次 Planner + 2 次 Decision。每个 R02 实测终态均未出现工具错误。

对照的原问题总耗时约 3.40 秒，修改后约 3.66 秒。这是单次样例的耗时，不作为稳定性能结论；新增真实信息获取需要多一次 Decision，纯目录问题不再执行知识检索。

验证前后原会话对象和全部八条消息一致，`conversation_unchanged=true`。

原始记录：[2026-10-10-r02-project-info-live.json](D:/学习/rag实战项目/rag-knowledge-base/docs/validation/2026-10-10-r02-project-info-live.json)。

## 版本与边界

| 项目 | 版本 / 身份 |
|---|---|
| 新工具 | get_project_info_v1 |
| Decision | engineering_agent_decision_prompt_project_info_v6 |
| Decision hash | 5c0b44774708eef853f174f8fb292e806d64acd8080ca2ac82ce016c28dcd5d5 |
| Planner | engineering_planner_project_info_prompt_v4 |
| Planner hash | b35d796685ea1d6fe87921eeaed3cd95d10135f13a498d5ab0a5f5c0bf1dfe87 |
| Engineering 模型可见 toolset hash | a98550613a0353575e3eae6f39b4695e2c5592bca571c5540904ebee770845b0 |
| R01 模型可见 toolset hash（保留） | 5b1cc58be8a9c289972f1ee4951f41e74f68d2952f66172b5c3fac6db75de267 |

R02 查询的是平台绑定事实，不提供目录导航、项目概览或代码行为答案。自然项目概览属于 R03；顶部目录显示和绑定入口属于 R04；历史详情归属风险属于 R10。没有同时处理这些独立问题。

运行中的后端需要重启才能加载新工具和 Prompt。此次未重启真实服务，未变更真实绑定或聊天记录，未改其他任务的 CI、运行手册及工具调用评测 v2 文件。
