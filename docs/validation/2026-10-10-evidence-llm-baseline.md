# LLM 证据需求改造前的规则基线

日期：2026-10-10。基线标签：`evidence-rule-v5-baseline-20261010`。

## 1. 本地源码身份与推送边界

改造前 HEAD 为 `bdd9faf6addc1ec633de3165a757cb3c2ca866f3`，相对 origin/main 有两个未推送提交。工作区另有 R01 当前请求、R02 项目绑定、R03 项目概览、R10 消息展示、工具评测 v2 与设计文档等未提交工作。

本次按项目所有者要求，先将这些本地工作保存并推送为规则基线，再在 `feat/evidence-requirement-llm-v1` 分支实施候选替换。基线的精确提交以标签所指 SHA 为准；本文件不伪造尚未生成的提交号。

业务指纹为 `69951bcb7c87f01ecb3fb5f8e45d57e82f7257a0a81d646bfcba0a7ede7c198b`，107 个文件。指纹口径为 core/api 和依赖配置；.env 仅作本地不透明完整性哈希，文件与凭据不提交。基线保留 Router v5、知识 Planner overview v5、Decision overview v7、Reader targets v4、code_search v7、ProjectInfo 文档入口 v2。

## 2. 依据本地代码复核的接口接缝

- Unified 中 Router 独立产生 requirement，不接收知识 PlannerOutcome；候选应替换该位置，而非在其后追加另一份要求。
- Runtime、执行适配器、Verifier 及 VerificationResult 都做严格类型/跨字段检查，不能仅用新提示词或一个 JSON 字典完成替换。
- 正文 evidence 强制真实路径、正行号与 snippet；列表、定位、候选需要独立且可引用的材料表示，并适配 API、V2 Activity 与 HTML。
- Reader targets 已包含对象定义、content_complete、截断原因等事实，应传递这些信息，不再次让模型签发来源或完整性。
- 旧恢复条件要求仍能取证，不能直接用于“材料已有，只需修正引用”。提交修正需要独立恢复类别，并继续消耗剩余决策额度。
- 产品公开 token 统计主要来自 Decision，新增需求调用须单独计量；执行 deadline 不是覆盖规划阶段的全链硬期限。

实施边界和对比组合见 [替换计划](../design/engineering_requirement_llm_replacement_plan.md)。候选默认不开启，不按旧 R01 通过率宣称当前版本质量。

## 3. 离线检查发现及修正

首次运行当前 CI 模块和相关改动模块，共 65 个模块：1261 passed、12 failed、10 skipped、3 warnings；外部及生产 8000 连接尝试为 0。初次结果保留在 `data/runtime/llm_requirement_prebaseline_zxye_s3u/`。

12 个失败的原因与改动：

1. 九个 Scripted 产品评测被静态六工具假设判为 INVALID；产品已有 get_project_info。新的记录固定声明实际启用集合，每次 Decision 必须一致；未知工具扩张仍判无效。历史未声明记录继续采用原六工具口径。
2. 一项 Fake SDK 联合验证暴露评测 manifest 仍写 Planner reference v3 / Decision current_request v5。改为与实际产品一致的 overview v5 / overview v7；真实调用 metadata 仍严格比对，未弱化身份校验。
3. 两项启动测试只提供 root 字段的旧项目假对象，装配新增绑定工具前即失败。改为真实 EngineeringProject，检查当前 profile，保持原初始化失败隔离断言。

评测器独立版本升为 `tool_calls_v2.3`。历史题集、Gold、R01 原始调用与报告未修改；没有重跑真实模型来“改善”旧成绩。

工具评测 results 目录沿用项目历史快照的 `-text` 属性，保留原始字节，避免 Windows 自动换行转换破坏 manifest 中的调用/题目 SHA。提交前对已完成记录的暂存字节再次验证。

修正后涉及的三个模块：101 passed、2 warnings。新负例检查未知工具扩张与单步 toolset 漂移。已有前端检查：29 passed。结果分别保存在 `data/runtime/llm_requirement_prebaseline_recheck_20261010_a.xml` 和本轮终端输出。

65 个模块的最终联合复验：**1274 passed、10 skipped、3 warnings，218.27 秒**，外部及生产 8000 连接尝试为 0。结果保存在 `data/runtime/llm_requirement_baseline_final_bc2mzh41/`。依赖警告与环境条件跳过按原记录保留，不当作通过或模型质量成绩。

本次不请求生产服务、不重启、不写真实知识库或聊天数据库；临时数据均在工作区内的忽略目录。运行结果只是离线回归，不是 LLM 替代实现或当前端到端模型质量验收。
