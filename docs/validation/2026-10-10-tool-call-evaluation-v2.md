# 当前 Engineering 工具调用评测 v2：首轮真实基线

**第二层已有当前版本、可重算的真实结果；本轮没有达到全面通过。** 开发集自动 PASS 为 **27/48（56.3%）**，新题为 **15/24（62.5%）**。主要缺口是取得正确材料后误拒答、多材料任务漏读、支持范围误判和错误恢复。完整答案与 HTML 产品端到端质量没有在本轮验收。

执行日期：北京时间 2026-10-10。开发集实际调用为 01:19:34～01:23:02，新题为 01:23:31～01:25:24；manifest 保存 UTC 时间。项目所有者已授权开始，启动前已告知。

## 运行版本与范围

- 使用当前 `api.app._build_engineering_project_runtime -> EngineeringAgentFacade`，实际调用 DeepSeek `deepseek-chat`。当前工作区包含另一对话的 R01 修复；不是只测历史 Git HEAD。
- HEAD：`bdd9faf6addc1ec633de3165a757cb3c2ca866f3`；实际业务 SHA：`f2ed09e1e55f38437485e57a716cbf5d20a5ff1e02dd4eabee15d1596818d3bc`。
- 真实运行评测器：`tool_calls_v2.2`；冻结评测器 SHA：`1c9c411127400063763e1ef624d1301579704be8515b8f6576327874378937aa`。
- 完整 72 题 SHA：`00449e755b7d4a39b82607368e5473a577444ebdf6091c4da03c590e59d1b4c2`；评分规则 SHA：`1ebdbd8ec69c7a048e7aa543fa737e9785c16afb5924c8a3e72e9d164653e841`。
- Decision 为 `engineering_agent_decision_prompt_current_request_v5`，Planner 为 `engineering_planner_references_prompt_v3`，Context 为 `engineering_context_references_v2`。独立单轮没有历史，Context 不产生模型调用。
- 保留 5 次逻辑决策 / 4 次工具调用 / 2 次工具错误、Decision 输出上限 1200、一次生产解析修复、SDK 重试 0。评测器没有任务级重试。
- 七工具注册中六种可调用；`knowledge_search` 在主链禁用。知识由前置规划/检索处理，不能记作模型调用第七种工具。
- 开发采用固定 Requests 与小 Git fixture；新题采用固定 urllib3。每个项目的 upstream commit、声明 patch、Git 状态和全部文件 SHA 均封档。
- 知识输入为经校验的 37 篇基础语料，复制成新 managed 库，实际 215 chunks、BM25。这个运行时库的 identity 是 `managed-v1-1 / verified=false`，不是线上用户上传/删除后的可变库，也不是 verified backend。

两个正式运行的业务、评测器、规则、知识内容和运行配置完全一致。每题前后检查版本；运行后检查 fixture，均未变化。没有启动/重启 API、向 8000 服务发请求、改生产库或改变共享业务文件。

## 原自动结果

自动分在运行前冻结；下表不掺入后续源码复核。

| 集合 | 计划 / 实际 / 有效 | PASS | PARTIAL | FAIL | 无效 / 未运行 |
|---|---:|---:|---:|---:|---:|
| 开发集 | 48 / 48 / 48 | 27（56.3%） | 17 | 4 | 0 / 0 |
| 新题验证 | 24 / 24 / 24 | 15（62.5%） | 5 | 4 | 0 / 0 |

| 任务组 | 开发集 PASS / PARTIAL / FAIL | 新题 PASS / PARTIAL / FAIL |
|---|---:|---:|
| 六工具目标任务 | 14 / 10 / 0（24 题） | 7 / 4 / 1（12 题） |
| 多材料取证 | 5 / 4 / 3（12 题） | 5 / 1 / 0（6 题） |
| 缺失、歧义、续读、恢复 | 3 / 3 / 0（6 题） | 0 / 0 / 3（3 题） |
| 无需工具及边界 | 5 / 0 / 1（6 题） | 3 / 0 / 0（3 题） |

| 过程指标 | 开发集 | 新题 |
|---|---:|---:|
| 必需材料获取，按材料义务计 | 54/64（84.4%） | 25/32（78.1%） |
| 有材料目标的整题材料齐全 | 36/43（83.7%） | 16/21（76.2%） |
| 不可替代工具义务覆盖 | 19/19 | 8/8 |
| 已解析执行调用的目标正确 | 69/72（95.8%） | 34/35（97.1%） |
| 合理首步，有明确首步判据的题 | 30/31（96.8%） | 14/15（93.3%） |
| 首次动作解析有效 | 116/121（95.9%） | 56/59（94.9%） |
| 生产修复后的动作解析有效 | 119/121（98.3%） | 59/59 |
| 解析修复成功，实际触发为分母 | 3/5 | 3/3 |
| 多材料过程通过，材料/依赖/停止均满足 | 5/12（41.7%） | 5/6（83.3%） |
| 已触发工具故障的恢复 | 1/1 | 0/1 |
| 停止行为符合冻结契约 | 31/48（64.6%） | 16/24（66.7%） |
| 正向任务误拒答 | 13 题 | 7 题 |

“目标正确”允许合法定位、已取得的部分目标及声明故障目标，不代表该调用足够或高效。重复读取同一导入行可能目标合法却耗尽预算，必须结合材料覆盖与整题停止分析。不可替代工具义务的 27 个观察机会也不能当成全部题目的成功率。

恢复仅实际触发了两次，一成功一失败。`dev-042` 直接 Reader 绕过了声明的搜索故障，是任务通过，恢复分母 N/A；不能把它算作恢复成功。原自动 Gold 对部分合法替代较严格，下面的复核单独处理。

## 六工具的实际覆盖

调用数量统计整条链，目标题 PASS 只统计每工具预先安排的 4/2 道目标任务。

| 工具 | 开发实际执行 | 新题实际执行 | 开发目标题自动 PASS | 新题目标题自动 PASS |
|---|---:|---:|---:|---:|
| calculator | 4 | 2 | 4/4 | 2/2 |
| code_search | 15 | 11 | 3/4 | 1/2 |
| read_project_context | 35 | 16 | 4/4 | 2/2 |
| changed_files | 7 | 2 | 0/4 | 0/2 |
| git_diff | 6 | 2 | 3/4 | 2/2 |
| find_tests | 5 | 2 | 0/4 | 0/2 |

`changed_files` 的六道目标题和 `find_tests` 的六道目标题均取得要求的材料，却都在最终阶段拒答。它们的工具结果可以正确，当前产品仍无法稳定完成这些请求。`git_diff` 开发目标中的 `dev-018` 是下文的合法辅助路径，复核后目标题为 4/4；原自动分保持 3/4。

全部 72 题没有解析出的越界尝试，也没有越界执行。开发边界题 `dev-048` 未读注入文档即误拒答，模型没有实际接触文件中的注入内容。这不能作为提示注入抵抗能力已经通过的证据，也没有验证真实越界动作被护栏拦截的在线分支。

## 开发助手源码复核

复核身份是 **developer_assistant / Codex**，不是独立人工评审。复核了全部 30 道非 PASS，再抽查 20 道自动 PASS，共 50 题。未逐题复核的 22 道通过项沿用自动分，清单见各 `review_summary.json`。

同时核对全部 fixture / Gold 文件 SHA，并将记录中 780 条 Reader 正文行和 81 条搜索命中行逐条与冻结文件比较，均一致。这是记录来源检查，不是公共答案全部事实的检查。

| 题号 | 原自动分 | 开发助手裁决 | 依据 |
|---|---|---|---|
| dev-018 | PARTIAL | PASS | 先 `changed_files` 确认目标变更，再取正确 diff，是合法辅助步骤，自动规则未枚举 |
| dev-034 | PARTIAL | PASS | 同名 `TestCaseInsensitiveDict.test_getitem` 也存在于 `tests/test_structures.py:20-22`，模型实际读到；Gold 只列了 `tests/test_requests.py` 的另一处定义 |
| dev-039 | PARTIAL | PASS | 一次 matching 读到 First.run、Second.run 两个具名定义和正文，完成材料及消歧语义；不能据此声称覆盖了 symbols 的 ambiguous 枚举及两次调用顺序 |
| val-019 | FAIL | PARTIAL | 短名 matching 的 not_found 足以证明限定名不存在；但随后被引用护栏拒答，停止原因仍不符合预定契约 |

应用显式复核、其余题沿用自动分后，开发为 **30 PASS / 14 PARTIAL / 4 FAIL**，新题为 **15 PASS / 6 PARTIAL / 3 FAIL**。开发通过率为 30/48（62.5%），新题仍为 15/24（62.5%）。这些是标明评审身份的补充口径，原自动 `scores.json / summary.json` 和指标未覆盖替换；Gold 没有在见到模型成绩后改写。

逐项理由与源码/调用定位分别见 [开发复核](../../evaluation/tool_calls_v2/results/live_dev_20261010_r01/review_report.md) 与 [新题复核](../../evaluation/tool_calls_v2/results/live_validation_20261010_r01/review_report.md)。初始待复核队列另存 `reviews.pending.json`。

## 主要问题与下一步优先级

**P0：列表、定位及候选资料没有对应的可引用项目证据。** 13 道目标题取得正确材料后仍拒答：`dev-006, dev-013～016, dev-021～024, val-007～008, val-011～012`。实际记录出现 `ANSWER_EVIDENCE_REFERENCE_MISSING`；`dev-015` 额外出现 `REQUIRED_EVIDENCE_MISSING`。

当前 `core/tool_agent/runtime.py:1104` 的 Observation 转换生成知识、Reader 正文和 git_diff 来源，没有为 code_search、changed_files、find_tests 的定位/集合/候选结果生成项目 public evidence。前置检索有时带来通用知识引用，但不能替代这些仓库事实。删除文件清单还被路由成 `PROJECT_CODE_V1`，要求已删除源码的正文。

下一步应先明确定位/变更集合/候选/查缺结果的来源契约，让只需要列表的任务能基于真实结果结束，并对删除文件任务校准取证要求。不应为提高成绩取消引用检查、引用无关知识块，或要求模型无目的地再读其他源码。这一修复会涉及现有证据交接，需单独形成业务变更，本轮未实施。

**P1：多材料任务缺少剩余义务与有效进展。** `dev-027, dev-035` 反复读取实现和导入行，没有去配置文件或测试文件；`dev-030, val-018` 取得实现/diff 或两个实现后，四次工具用完，测试只定位未读。`completed` 也可能材料不全。先处理跨文件依赖、同文件多目标合并读取及剩余预算规划；保留 5/4/2，不先用加预算掩盖策略问题。

**P1：合法读取被误判为不支持。** `dev-032, dev-048, val-004, val-020` 的第一个动作即 `UNSUPPORTED_REQUEST`，工具未执行。冻结源码与离线路径证明目标可读。应核对支持范围说明与决策行为，保留写入/执行的真实拒答边界。没有原始模型输出或 CoT，不能臆测它是因为某个词而拒答。

**P1：解析与错误恢复仍薄弱。** `dev-028, dev-033` 已取得材料，最后动作 `ACTION_SCHEMA_INVALID`，一次生产修复后仍 `ACTION_PARSE_FAILED`；本轮没有保存原始输出，具体违规字段未细分。`val-021` 的 Reader 临时错误实际触发后，模型重复相同 definition 调用，被 `AGENT_DUPLICATE_TOOL_CALL` 停止；没有用其他合法 target 恢复。应分别检查动作协议/修复反馈和失败后的替代路径，再以新版本验证。

**P2：查缺与评分等价路径。** `dev-037, dev-038, val-019` 没有编造缺失实现，但走了“尝试 final_answer 后被引用护栏拒答”，不是预期的 `INSUFFICIENT_INFORMATION`。应区分不存在与有材料但不够结束，给用户准确反馈。评分下一版本可补入本次已源码确认的合法替代和限定名/短名查缺等价；必须建立新规则身份，保留本次自动基线。

下一轮先以这些题作开发/回归诊断。修复后的新题需另行冻结；本轮 24 道新题现已公开并用于失败分析，之后重跑只能称为回归，不能继续当作从未见过的独立验收集。扩大领域与多次运行稳定性仍需后续建设。

## 实际调用与资源

| 资源 | 开发集 | 新题 | 合计 |
|---|---:|---:|---:|
| 实际 provider 调用，含 Planner/Decision/解析修复 | 174 | 86 | 260 |
| 逻辑 Decision | 121 | 59 | 180 |
| Planner | 48 | 24 | 72 |
| 额外解析修复调用 | 5 | 3 | 8 |
| 工具执行 | 72 | 35 | 107 |
| Input tokens | 822,610 | 418,199 | 1,240,809 |
| Output tokens | 14,267 | 10,452 | 24,719 |
| Usage 缺失的实际调用 | 0 | 0 | 0 |
| 单题全过程 p50 | 2.66 秒 | 3.03 秒 | 不合并 |
| 单题全过程 p95 | 6.69 秒 | 8.32 秒 | 不合并 |

总 token 为 **1,265,528**。这些是一次顺序运行的实测，不是并发性能或 SLA。资源合计可以汇总，开发/新题的质量率分别报告。

没有 provider/网络故障、记录器中断或版本变化。所有失败保留，没有为了好成绩补跑。当前业务至交付检查仍与冻结 SHA 一致。

## 可复现交付与验证

- [开发原自动报告](../../evaluation/tool_calls_v2/results/live_dev_20261010_r01/report.md)、[新题原自动报告](../../evaluation/tool_calls_v2/results/live_validation_20261010_r01/report.md)。每个目录含 manifest、冻结 cases、调用 facts、自动 scores/summary 与独立 reviews。
- [开发离线重算](../../evaluation/tool_calls_v2/results/live_dev_20261010_r01_recomputed_checked/report.md)、[新题离线重算](../../evaluation/tool_calls_v2/results/live_validation_20261010_r01_recomputed_checked/report.md)。两次重算均零模型调用，scores 与 summary 逐项等于原结果；原始文件 SHA 验证通过。
- 正式调用前，局部离线测试 **91 passed / 2 既有依赖警告**；本轮装配回放为 71 PASS / 1 PARTIAL，后者仍是删除源码清单的 Guard 缺口，不能当模型成绩。
- 交付时局部测试 **95 passed / 2 既有依赖警告**。没有跑完整 CI 或全仓回归。
- 正式运行后发现重算 CLI 用默认 gold_proof 模式判断退出码：真实模型重算内容正确，却因存在模型 FAIL 而返回 1。已只修复评测外围，让退出码按保存的真实 mode 判断，并记录重算时评测器 SHA；增加四个回归案例。最初两份重算也保留，修复后用新目录重新重算，未重跑模型。
- 除启动前对齐新 profile、检索 keyword 的观察器兼容，及上述运行后 CLI 修复，本轮没有改变题集/评分器、核心 Prompt、工具、Guard、API 或前端；另一对话的 R01 变更是被测业务输入，不归作本轮修复。

重算命令示例（run ID 必须新建）：

```powershell
python scripts/run_tool_call_evaluation.py --rescore evaluation/tool_calls_v2/results/live_dev_20261010_r01 --run-id analysis_dev_new
python scripts/run_tool_call_evaluation.py --rescore evaluation/tool_calls_v2/results/live_validation_20261010_r01 --run-id analysis_validation_new
```

本轮已补齐第二层的当前基线、失败证据、资源记录和开发助手复核。尚未补齐独立人工评审、跨领域与重复运行稳定性，以及第三层公共答案/多轮/HTML 产品端到端验收。面试时可以介绍已实际运行的评测流程和具体发现，不能把“建立评测体系”说成“当前系统全面通过验收”。
