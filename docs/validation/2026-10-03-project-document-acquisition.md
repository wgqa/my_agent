# 项目文档取证切片验证（2026-10-03）

## 保留结论

保留文档独立证据域 `PROJECT_DOC_V1`：用户明确要求依据绑定仓库的文档回答时，进入已有的缺证据取证流程。源码、变更、测试、理论与源码对照等原有 7 种 requirement shape 不变，Runtime 仍为 **5 次逻辑决策 / 4 次工具调用 / 2 次工具错误**。

本轮文档切片配对中，Requests 功能、安装要求与 smolagents Quick demo 三题从 **0/3 完成变为 3/3 完成**；逐项答案都得到实际读取内容的支持。其中 Quick demo 的公共引用预览仍被截断，不能把三题都算作完整引用展示通过。7 道源码题的工具名、参数、读取范围与状态逐项相同，源码答复质量仍有缺口。

此前先试了只改通用任务完成提示词，未改善 README 拒答，且出现一次 action schema / repair 失败；候选**未晋升，生产提示词按字节恢复**。两次实验分别报告，不合并质量指标，不改写此前搜索候选的负结果。

## 根因与整体边界

现有链路已经能够表示 `project_doc` 证据、搜索和读取文档、计算 missing groups、给决策模型发送可信控制状态、校验最终引用。但 Router 只有“文档与源码对照”档位，没有“依据文档回答”档位。文档单独查询可能落入 `NO_ADDITIONAL_REQUIREMENT`；若 Planner 先检索到通用知识，Agent 可以未查看指定文档就拒答。单纯增加搜索 scope 不能使它开始取证。

本切片只补齐这个证据域，沿用已有机制：

```text
明确文档证据请求
  → PROJECT_DOC_V1 / missing project_doc
  → 既有 acquisition control
  → code_search / read_project_context
  → 原有 finalization 与 E-ID binding
```

- 要求阅读、依据、总结、引用等操作，配合相对文档名（`.md/.rst/.txt`）或仓库文档范围；写作建议、文档概念、外部 URL / 绝对路径不能仅因文档字样激活新档位。
- 文件名先从意图文本中遮蔽，避免把 `docs/read.md` 的名称当成阅读操作，或把 `docs/source.md` 当成源码任务。路径分类复用共享文件分类器；测试路径不冒充文档域。
- 原有变更与测试、文档与实现对照、理论与源码对照的优先级保留；明确源码请求仍走原有路径。
- 新档位只要求实际 `project_doc`，不要求附带源码或知识命中。局部测试验证了 Planner 知识检索缺失或不相关时，实际文档与有效引用仍可完成。
- 不新增工具、模型调用层、特批预算或恢复循环。默认搜索仍为 v5，长期 Task / Evidence / Execution v2 契约继续暂缓。

这是有界 lexical minimum，尚未提供指定路径与每句结论的语义绑定。它不证明模型在所有措辞下都能识别文档意图，也不证明任意 `project_doc` 必然是用户所指定文件。

## 冻结与执行范围

两个阶段分别在运行前冻结 catalog、候选身份、代码快照、source pins 和晋升条件。同一份 12 题包含之前 8 题、2 题文档变体、1 题缺失文档负对照、1 题通用文档知识负对照；每阶段旧/新各一次，交错执行，两个仓库分别使用隔离 App 进程和数据库。

| 项目 | 固定输入 |
|---|---|
| baseline HEAD | `d937046d2c0c8d41a74693f879ff41091a861ab9` |
| Requests pin | `b25c87d7cb8d6a18a37fa12442b5f883f9e41741` |
| smolagents pin | `c30b115286e000e98711fae5e85993547b73d826` |
| Provider / model | DeepSeek / `deepseek-chat` |
| Planner | `gate3_planner_prompt_v1` |
| 文档阶段两组 Decision prompt | `engineering_agent_decision_prompt_unified_kind_aware_grounded_v1` |
| KB | `870e5864df67`；37 文件 / 215 chunks；BM25 |
| 输出上限 / 格式修复 | 1200 tokens / 至多 1 次；各组相同 |

完整 SHA 与配置在 [实验归档](../../evaluation/task_completion_20261003/README.md)。每阶段各 **24 个用户请求**，其中 10 个经 SSE v2；全部 HTTP/SSE 有效、工具错误为 0，全部符合 5/4/2。Planner 调用和格式 repair 单独计数，不能把 24 个请求称为 24 次模型调用。

## 客观运行结果

| 阶段 / 组 | completed / refused / failed | 逻辑决策 | 工具 | 格式 repair | 实际 provider 调用 | input / output tokens |
|---|---:|---:|---:|---:|---:|---:|
| 提示词 / baseline | 8 / 4 / 0 | 33 | 21 | 0 | 45 | 199477 / 7167 |
| 提示词 / candidate | 7 / 4 / 1 | 33 | 21 | 2 | 47 | 224442 / 6265 |
| 文档域 / baseline | 7 / 5 / 0 | 29 | 17 | 2 | 43 | 187919 / 7416 |
| 文档域 / candidate | 10 / 2 / 0 | 39 | 26 | 1 | 52 | 242846 / 7396 |

合计 **48 个真实用户请求 / 187 次实际 provider 调用**。文档候选为新增取证付出了更多调用；没有扩预算。Requests 功能题用满 5/4 上限，不能由此认为当前策略已有很大余量。

提示词阶段的 S01 记录为 `ACTION_SCHEMA_INVALID`，格式修复后仍 `ACTION_PARSE_FAILED`；现有元数据不能进一步证明具体格式错误，也不能归因为输出截断或预算耗尽。该阶段 R04/D02 仍零工具拒答。D01 在第一阶段两组都能回答、第二阶段 baseline 拒答，说明单轮结果存在模型波动。

## 文档阶段逐题审查

这是同一实施助手对原始读取、完整回答与公共证据的开发审查，**不是独立验收，也不是 Holdout**。PASS/PARTIAL/FAIL 按“所问关键行为是否得到实际读取支持”和“整份答案及公开引用是否完整”分别记录，不能用 `completed` 替代正确率。

| 题目 | baseline → candidate（所问 / 整份） | 核对结果 |
|---|---|---|
| S01 CodeAgent 单步 | PARTIAL/PARTIAL → PARTIAL/PARTIAL | 两组都读 1696–1756；遗漏 1760–1764 的输出保存与 ActionOutput，公共片段也被截断 |
| S02 ToolCallingAgent 参数 | PARTIAL/PARTIAL → PARTIAL/PARTIAL | execute_tool_call 已读取，state 替换 helper 未读，未完整解释替换边界 |
| S03 PythonInterpreterTool | PASS/PASS → PASS/PASS | 限制参数、求值与 Stdout/Output 拼接均有对应读取 |
| S04 SQL 示例 | PARTIAL/PARTIAL → PARTIAL/PARTIAL | 读取 sql_engine 50–69；CodeAgent 注册在 76 行，回答引用却没有覆盖它 |
| R01 prepare_request | PASS/PASS → PASS/PASS | 按原有审查口径，cookies 合并、prepare 调用及 netrc 条件有支持 |
| R02 环境配置 | PASS/PASS → PASS/PASS | 读取完整方法 750–779，代理与 CA bundle 条件及 Session 合并准确 |
| R03 Response.json | PASS/PARTIAL → PARTIAL/PARTIAL | 两组引用未读的顶部异常导入；candidate 另把条件回退说成“最终都会尝试”，与成功分支直接返回不符 |
| R04 README HTTP 功能 | FAIL/FAIL → PASS/PASS | 从零工具拒答变为搜索后读 README 1–50；三项功能与实际文档、公共 E6 相符 |
| D01 README 安装要求 | FAIL/FAIL → PASS/PASS | 读 README 3–63；Python 3.9+ 与 pip 命令有支持 |
| D02 Quick demo | FAIL/FAIL → PASS/PARTIAL | 读 README 23–83；安装、CodeAgent、WebSearchTool、run 正确，但公共 E6 的 2000 字符预览止于 demo 之前 |
| D03 只允许缺失文件 | PASS/PASS → PASS/PASS | candidate 搜索指定标记无命中后有界拒答，没有替换成其他文件；没有直接 Reader 存在性探测，不能把无搜索命中称为文件不存在的证明 |
| K01 通用文档知识 | FAIL/FAIL → FAIL/FAIL | 两版都未强加仓库取证，但原有 Planner fallback / 引用门槛仍造成不必要拒答 |

所问行为：baseline **5 PASS / 3 PARTIAL / 4 FAIL**，candidate **7 PASS / 4 PARTIAL / 1 FAIL**。整份答案与公开引用：baseline **4 PASS / 4 PARTIAL / 4 FAIL**，candidate **6 PASS / 5 PARTIAL / 1 FAIL**。R03 的工具链与 Router 约束相同，但表述出现质量回归；单轮不能把它因果归于文档档位，也不能宣称“没有任何质量回归”。逐题记录见 [manual_review.json](../../evaluation/task_completion_20261003/document_source_slice/manual_review.json)。

## 保留代码与离线检查

真实文档实验完成后补充了文件名遮蔽，解决 source/code/read/cite 出现在文件名里时的误判。**付费测试时的 candidate snapshot 原样保留**；最终代码另存 retained snapshot。离线核对 12 题的 Router profile/groups/min paths/version 均与付费候选一致，原有 7 个 shape 完全相同，13 个保护文件原样不变；这不等于最终文件又跑了一轮真实模型。

相关 15 个文件局部回归 **278 passed / 3 warnings**。随后将历史 Router 身份防漂移用例移入 CI 会执行的新文档模块，单独重跑该模块 **31 passed / 2 warnings**；这是验证清单调整后的复验，不累加为 309 个不同测试。一次复验因显式 temp 父目录不存在导致 fixture setup 错误，创建父目录后原样通过，记录在 final_test_scope.json。

CI 与运行手册清单逐项一致，共 35 个模块。历史 Integration v7 的 System B Router 仍冻结为 v1，历史 manifest/dataset/结果没有重标。没有执行完整 CI job、全量 pytest、Holdout、部署或推送。

## 后续债务

本次只将 TD-ROUTER-01 的文档取证缺口标为部分解决。TD-ROUTER-02 的过度约束风险、TD-TOOL-02 的 helper / 方法尾部取证、TD-VERIFY-01 的语义与公共引用范围，以及 TD-PLAN-01 / TD-VERIFY-02 的非仓库任务误拒答继续开放。

下一步优先把**实际读取内容与公共 Evidence 的范围一致性**做成一个明确切片，再处理多项问题的完成度；不要直接扩大 Router 词表、逐题增加分支或给 Runtime 特批次数。本轮已足以保留文档档位，不足以证明完整工程 Agent 已达到目标能力。
