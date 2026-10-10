# 证据需求替换 M1/M2：本地源码审查与阶段交付

日期：2026-10-10。本文记录工程接口与离线检查，不是模型任务质量验收。

## 1. 版本与实施顺序

- 规则基线：main 提交 `f3c9e28aec8b29ccfcad9476ea88871aacbefa06`，已推送；远端标签 `evidence-rule-v5-baseline-20261010` 指向同一提交。
- 候选分支：`feat/evidence-requirement-llm-v1`，从该规则基线建立，不改写 main 或旧 Router v4/v5。
- M1 接口提交：`c617e1840f5e92eac41870601870895bdf11332a`，规则/模型实现、冻结合同与重放入口；提交前 132 个离线用例通过。
- M2：统一入口、影子装配、单独计量和传输兼容。检查点标签为 `evidence-requirement-shadow-v1-20261010`；本轮只交付这两个可独立审查的阶段。
- M3/M4 仍待实现。模块能生成 LLM 合同，不意味着执行器已能按目标取证或判定完成。产品和 Unified 装配层都会拒绝 `llm + goal_v2`，避免新合同误入旧严格校验器。

## 2. 本地源码确认的实际缺口

本轮直接执行 `route_engineering_evidence_requirement("解释 A、B 两个函数的完整实现")`，Router v5 返回 `NO_ADDITIONAL_REQUIREMENT`。加上明确源码线索后，`"读取 src/a.py 源码，解释 A、B 两个函数的完整实现"` 返回 `PROJECT_CODE_V1`；取得 A 的一条真实正文并引用后，旧校验器可以完成，并没有验证 B。

这两个反例说明需求识别与逐目标覆盖都必须改造，不能将问题全归因于 Decision 模型。反例用于架构分析，不计作新评测题的通过率。

已复核的接缝：

1. `core/unified_engineering_runtime.py` 的知识 PlannerOutcome 与证据 requirement 互相独立。新 provider 替换原 Router 调用，保留一个有效 requirement，不在其后合并第二份要求。
2. `runtime_models.py`、执行适配器及 `engineering_verification.py` 的正文证据/要求/校验结果都有严格类型和跨字段不变量。元数据列表不能塞进正文类型或伪造 0 行号。
3. Reader v4 的实际请求是 `path + target`，target.kind 可为 file/window/definition/symbols/matching；不是虚构的 targets 数组。返回的 regions/targets 包含定义、截断与 content_complete 等程序事实。M3 应从实际结果登记对象及覆盖，不能让 LLM 签发完整性。
4. 旧终结校验的 recovery_allowed 只允许继续取证；缺引用、引用无效但材料已有，不走此分支。M4 应区分提交修正与取证恢复，最多一次修正并消耗原 Decision 额度，不重置工具/错误预算。
5. 原执行统计只汇总 Decision 调用，原期限从工具循环开始。新增需求调用若混入 Decision 或宣传成严格全链期限，都会产生错误指标。

## 3. 已实现接口

`core/engineering_requirement_contract.py` 提供版本 `engineering_evidence_requirements_v2`。模型只能输出需求：目标描述、当前请求依据、可接受来源、材料深度、对象/变更范围线索及完整范围要求。程序分配 g1..g8，冻结输入与合同 SHA。不能输出证据 ID、完成状态、权限、工具动作或预算。

`core/engineering_requirement_planning.py` 提供同一职责的两种实现及选择器：

| 选择 | 有效 requirement | LLM 需求调用 | 当前执行状态 |
|---|---|---|---|
| 默认 rule/legacy | 原 Router v5 类型 | 0 | 保留原路径和公开结果 |
| 显式 rule/legacy | 原 Router v5 类型 | 0 | 可记录实验身份，使用合作式全请求期限 |
| shadow/legacy | 原 Router v5 类型 | 1 | 已接通；候选只保存在本轮 outcome |
| rule/goal_v2 | 原规则约束的无损适配 | 0 | 仅合同生成/重放可用；执行禁用 |
| llm/goal_v2 | 模型冻结目标 | 1 | 仅合同生成/重放可用；执行禁用 |

适配器不补写旧规则没有识别出的具名目标，保留 profile、证据组、路径数和 Router 版本。规则 v4/v5 都可选择，不修改冻结 profile。

LLM v1 使用已有模型服务的单独调用：temperature=0，20 秒 SDK timeout，自动重试 0，输出上限 1600 token。期望的超时、服务错误、无效 JSON/额外字段/重复键/过深 JSON/截断输出有明确失败码；程序错误继续抛出。合法但错误的解释不会偷偷改用规则。

选择器支持声明的 `rule_before_freeze` 回退，用于未来产品试运行；严格对比用 `disabled`。回退仅在没有合法合同前发生，记录原失败、有效规则版本与实际调用成本。产品本阶段只允许 rule/shadow，不开放该执行路径。

## 4. 追踪、重放与成本边界

- Metadata 独立版本为 `engineering_requirement_planning_metadata_v1`，保存有效实现、候选版本、输入/合同/提示词 SHA、provider/model、尝试调用数、服务报告的 token、时延与失败/回退状态。
- 需求调用独立于 `execution.decision_llm_calls`。null token 表示服务没有报告；不估计，不写成 0。知识 Planner/Context Resolver 的成本尚未在此字段中合并，因此这些字段不是全部模型开销。
- 原 API/HTML 的 V2 stream 沿用现有 answer_start/answer_delta/final/done 及 Activity 协议。影子 final 增加安全 metadata；默认 rule 结果不新增该字段，不发送目标描述、输入文本、原模型输出或隐藏推理。
- 开发者可显式导出 artifact，并通过 `load_requirement_artifact` 校验身份、字段与合同 SHA，离线重建已冻结的需求。artifact 包含用户输入/目标，需按评测数据管理；不会自动写入聊天内容或应用日志。
- 重放冻结需求不会再次调用模型，也不保证在线模型再次采样相同，更不等同于重放完整工程回答。完整重放还需要固定项目、知识库、工具观察及版本。
- 每轮 outcome 均为局部变量，共用项目 runtime 不保留上一轮候选或证据；并发两轮验证了目标与 E-ID 各自独立。
- 显式实验路径按合作方式检查取消和请求期限，不强杀已经在执行的调用。正式三组对比必须统一期限口径并记录配置。

## 5. 离线验证与范围

最初 M1 的 132 个用例通过。M2 初次联调修正了测试中的每轮随机 call_id 比较、旧 Router monkeypatch 位置及真实 stream 事件名；没有放宽产品条件或修改 Gold。相关 10 个模块复验为 214 passed。

随后 68 模块整套检查为 1433 passed、12 failed、10 skipped、3 warnings。11 个失败来自其他历史测试仍拦截旧 Router import；逐个迁到新入口，保留原断言。另 1 个启动测试原本依赖本机 verified corpus，补上与同组测试一致的离线 backend 假对象，去掉环境依赖。初次结果保留在 `data/runtime/requirement_offline__k1b2nsy/`。

修正后 8 个相关模块复验：231 passed、3 warnings，socket 拦截次数 0，执行期间代码未改变；记录在 `data/runtime/requirement_offline_gdlq7xn0/`。前端 Node 检查为 30 passed，包含影子 metadata 对 V2 流协议的兼容。

68 模块完整联合复验：**1446 passed、10 skipped、3 warnings，208.68 秒**。pytest exit code=0，父进程 socket/DNS 拦截次数=0，运行期间代码未改变。Junit 和输入代码的 HEAD/变化文件 SHA 清单位于 `data/runtime/requirement_offline_33g4jzrq/`；测试输入为 M1 提交加该清单中的 M2 文件。回归后仅追加本文结果记录及计划状态，不改被测执行代码。依赖警告与环境跳过原样保留，不计作模型任务成绩。

检查命令：`python -X utf8 scripts/run_requirement_offline_regression.py`。脚本读取当前 CI 模块并追加相关架构测试，生成新的忽略目录、独立测试数据库、Junit、源代码 SHA/变化文件哈希清单；阻止父 Python 进程的外部 socket/DNS 与生产 8000 连接。子进程测试继续使用各自现有离线假对象，不能把父进程拦截计数夸大成所有系统调用的审计。

本轮未调用真实模型评测，未修改实际知识库、聊天库或 .env，未主动重启生产服务。阶段代码没有形成正式工具层成绩，也没有形成端到端质量结论。

## 6. 后续切片的必需门槛

M3 必须把真实定位、列表、候选、正文、变更、计算和绑定材料与单独目标关联；缺对象或正文截断不能由另一对象填补。API、V2 Activity 与 HTML 要一起支持新增元数据材料，保留旧类型的引用语义。

M4 必须补齐逐目标引用与有限提交修正，保持取消、权限、重复调用、无进展、5/4/2 预算和 answer/status 不变量。之后才开放执行型 LLM 模式，并按计划冻结最新题集/Gold/版本/配置，提前向用户说明正式模型评测范围。

简历当前可以描述可切换需求入口、冻结合同、影子对比与离线回归；不能写已完整替换并显著提升通过率。
