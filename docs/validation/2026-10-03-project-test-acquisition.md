# 仓库测试取证：修复范围与两阶段对照（2026-10-03）

保留测试取证域的一致性修复。原失败题 R06 可以读取实际测试、解释断言并给出准确的 pytest 命令；最终中文改写 T02 也正确完成。T03 虽然不再拒答，仍生成错误的 pytest 建议，不能算整题通过。当前切片没有关闭全系统拒答或语义正确性债务。

## 原因与改动边界

历史 R06 问的是仓库中哪项测试覆盖 `final_answer` 与其它工具同时调用的限制。已有读取器和公共 `project_test` 类型，但独立测试问题没有最低测试证据要求，`code_search_v5` 排除了测试文件，决策提示词还明确禁止它搜索测试。`find_tests` 要求先提供源码路径，适合寻找关联测试，不能直接替代按测试名称或断言定位。这三个接口没有对齐，模型连续搜索 `project_code` 后终止。

本轮只修改六个生产文件：

- `core/engineering_requirements.py`：Router v4 增加 `PROJECT_TEST_V1`，仅约束明确查阅仓库已有测试的请求，要求 `project_test`，不要求源码路径数量。旧八种 profile 的 evidence shape、混合任务优先级不变；通用测试设计、写测试建议和非本地引用不因此增加测试读取义务。
- `core/tool_agent/tools/code_search.py`：新增 Engineering 使用的 v7 契约，增加 `artifact_kind=project_test`。复用原搜索算法和共享文件分类器，原 any/code/doc 结果、排序、10 条/300 字符上限、文件大小及访问安全规则不变。v6 是未保留的 scope 实验，本轮没有采用它。
- `core/tool_agent/default_tools.py`、`integration.py`：系统通过封闭版本选择同时装配 spec 与 handler。旧调用默认 v5；模型不能传版本、根目录或 scope 参数；仍是原七种工具。
- `core/tool_agent/decision_prompt.py`、`api/app.py`：Engineering 选择与测试搜索一致的 grounded v2 提示词，沿搜索 → 读取 → 引用流程。补充测试函数范围读取与准确 pytest 选择器规则。旧 grounded v1 内容/SHA 与 legacy 装配保留。

**没有改 Runtime 循环、预算、Verifier、Reader、API/SSE schema、知识检索、Planner、目录结构或编辑/执行能力。** 每轮仍最多五次逻辑决策、四次工具调用、两次工具错误；现有一次解析修复不变。累计 provider 调用数包含 Planner 和解析修复，不能当作单轮决策数。此处提示词 v2 不代表启用长期 Task / Evidence / Execution Contract v2。

## 实验与冻结

两个阶段各八题、每题旧/新各一次，顺序交替；总计 **32 次真实请求 / 130 次 provider 调用**，没有付费重试或 Holdout。两个源码项目为干净固定提交：smolagents `c30b115286e000e98711fae5e85993547b73d826`，Requests `b25c87d7cb8d6a18a37fa12442b5f883f9e41741`。两边使用相同已验证 BM25 知识库 `870e5864df67`，保留上一轮 Engineering Planner 字段约束修复。

| 阶段 | baseline | candidate | 目的 |
|---|---|---|---|
| 测试域对齐 | Router v3 / 搜索 v5 / grounded v1 | Router v4 / 搜索 v7 / 初版 grounded v2 | 对齐最低证据要求、可用搜索域和工具选择规则 |
| 读取策略补充 | 上一阶段 candidate | 相同 v4/v7 + 测试定义范围/准确选择器规则 | 检查是否取得完整测试输入、断言及名称 |

提示词均保留实际发送的版本和 SHA。初版 v2 SHA 为 `3af156b283b30c5e0365561a22c62635192082324945cb6a18889db65f7a94e9`，最终保留 v2 SHA 为 `1544b0d3486651a72756ebf686e9c58181b91d9cc8265d3a673490f3c4e628ad`；两份开发候选快照分别冻结，不能用最新内容覆盖第一阶段。旧 grounded v1 SHA 仍为 `c465defe7f9504d7cfb137748ba96fb90cf7bf049c7ca7a93d3f7f56945ebcdf`。

第一阶段原样封存 37 个文件；本轮 17 个保护文件与此前三个切片归档的 83 个文件 SHA 不变。baseline 包括前序未提交的修复，不能仅用 Git HEAD 当对照。第一阶段使用原 Router 快照和旧装配身份；第二阶段两边均为新测试域，仅提示词规则不同。没有修改生产观察结果来满足评分。

## 逐题内容审查

PASS 要求所问任务由实际取得的材料支持，且命令可以准确定位目标。下面是同一开发助手核对固定源码与引用范围的结果，不是独立验收；三道测试题针对同一个测试函数，不能当作三个独立 bug 或统计泛化证据。

| 题目 | 第一阶段旧 / 新 | 第二阶段旧 / 最终新 | 关键结果 |
|---|---|---|---|
| R06 原测试拒答 | FAIL / PASS | PARTIAL / PASS | 最终读取 1815–1888 完整定义，解释 mock 并行调用及两项错误断言；pytest node ID 来自 Reader 返回的限定名 |
| T02 中文改写 | FAIL / FAIL | PASS / PASS | 首轮新读 1786–1846，缺后半段断言，随后 action 参数校验及一次修复失败；第二轮两边均完整读取并正确建议命令 |
| T03 按断言字符串定位 | FAIL / PARTIAL | PARTIAL / PARTIAL | 能取得断言，但最终仍只读 1856–1916，遗漏测试名称；命令错误且行号表述不准确 |
| T04 指定缺失测试标记 | PASS / PASS | PASS / PASS | 搜索无命中后有界拒答，没有替换测试或伪造执行；无命中不等于不存在证明 |
| S01 源码未知工具名分支 | PASS / PASS | PASS / PASS | 四次均读取方法定义 1453–1502，正确引用 `AgentToolExecutionError` 分支 |
| D01 README 版本与安装 | PASS / PASS | PASS / PASS | 读取 README，引用 Python 3.9+ 与 `python -m pip install requests` |
| K01 通用文档用途建议 | PASS / PASS | PASS / PASS | 合法不检索计划，零仓库工具和证据，不引入测试义务 |
| C02 计算 | PASS / PASS | PASS / PASS | 实际 calculator 返回 1073；零检索、零仓库证据 |

第一阶段：旧 **5 PASS / 3 FAIL** → 新 **6 PASS / 1 PARTIAL / 1 FAIL**；原三道测试题的正确范围发现从零到三次，但只有一道整题通过。状态 completed/refused/failed 从 **4/3/1 → 6/1/1**。

第二阶段：旧 **6 PASS / 2 PARTIAL** → 最终新 **7 PASS / 1 PARTIAL**；两边状态都是 **7/1/0**，因此状态分布无法体现语义差异。原题旧答案只读函数前半段，还错误描述 `stream_outputs=True`；最终新答案完整读取。T02 的第二轮旧侧也通过，不能把全部改善归因于新规则或宣称参数解析问题已根治。

T03 最终建议 `-k "do not perform any other tool calls"`，这是断言正文，不是测试选择器；使用本机 pytest 表达式解析器离线验证为语法错误。占位符 node ID 也不能直接运行。其引用范围没有测试定义，且实际函数从 1815 行开始，不在答案声称的 1856–1888 内。此前宽泛 `-k final_answer` 也对应多个静态测试声明。**没有对挂载仓库执行或收集测试**；上述诊断仅解析表达式与源码 AST。

第一阶段两次失败均为 `ARGUMENTS_SCHEMA_INVALID` 后一次失败修复，初始 finish reason 均为 `stop`。未记录失败原文或具体参数，不能声称原因是额度、输出截断或某个确定的非法参数。第二阶段没有解析修复，仍有 T03 语义错误。

## 验证范围与代价

- 阶段一相关 23 模块局部 **371 passed / 7 skipped / 3 warnings**，跳过为本机创建符号链接的权限限制。旧 profile 总数断言补入新类型后通过，原 shape 不放宽。
- 最终规则调整后六模块 **184 passed / 2 warnings**，包含新模块全部 **37 项**、长测试函数的名称/输入/尾部断言与 Reader → 公共正文衔接、历史身份、合法不检索、引用约束和 Provider 装配。两轮离线集合重叠，数字不累加。
- CI 与运行手册当前均为 **38 模块**；没有运行完整 CI job、全量测试或前端 smoke。
- 32 个请求全部通过 HTTP/API schema 与预算检查，16 个使用 SSE v2，单题两边相同传输。17 次成功读取的公共 snippet 全部逐字符匹配实际 Reader 返回内容；工具错误为零。
- 实际调用为 32 Planner + 98 Decision；阶段一两边各 33 次，第二阶段旧 31 / 新 33 次。总 input/output token 为 **586424 / 9746**。样本不能证明成本或延迟下降。

更严格的测试证据义务可阻止知识/源码替代仓库测试，但 lexical 识别仍有措辞边界。函数级读取仍受原 120 行 / 8000 字符上限约束，Python 以外的测试沿既有窗口读取，不保证长测试完整；没有增加自动执行或预算豁免。

## 剩余问题与下一步边界

保留本轮测试域闭环；TD-TOOL-02 / TD-ROUTER-01 属于局部改善。T03 继续证明 Structural Verifier 只能检查证据类型/引用，不保证命令、行号或每项结论的语义支持。R02 优先级概括与 C01 知识支持问题也未在本轮解决或重评。

下一步应优先评估“答案中的可核对产物如何关联实际取得的来源”，把命令建议、范围声明和不完整证据作为共同反例；没有充分设计依据时，不新增按题目放行、pytest 专用 Guard、额外循环或更大预算。长期任务契约和目录重构仍暂缓。

## 复核入口

- [第一阶段快照、manifest、结果与审查](../../evaluation/project_test_acquisition_20261003/manifest.json)
- [最终阶段 manifest](../../evaluation/project_test_acquisition_20261003/definition_policy_followup/manifest.json)
- [逐项内容审查](../../evaluation/project_test_acquisition_20261003/definition_policy_followup/manual_review.json)
- [pytest 选择器静态诊断](../../evaluation/project_test_acquisition_20261003/definition_policy_followup/pytest_selector_diagnostic.json)
- [无 Provider 分析脚本](../../evaluation/project_test_acquisition_20261003/analyze.py)

在本切片代码状态运行 `python -m evaluation.project_test_acquisition_20261003.analyze` 校验冻结边界。今后源码/文档变化可能触发版本错配，这是检查边界的预期行为；不要重写旧 manifest 来使它通过。真实重跑须新输出目录及显式 `--live`，受原 16 请求限制。
