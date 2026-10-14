# Task021：自主补证与真实四题对照

## 结论

建议保留小改动在实验分支，**暂不作为稳定 Agent 基线**。Planner 协议和主动取证明显改善，但真实变更分析出现来源真实、解释错误的交付，不能把 Gate 接受率当成用户任务成功率。本轮已停止，未补跑或扩大实验。

| 本轮同条件四题 | Task019 | Task020 | Task021 |
| --- | --- | --- | --- |
| 删除源码文件 | 拒答：旧 PROJECT_CODE_V1 | Planner 解析失败 | 完整正确：仅 retired_source.py |
| scale 实现 | 部分：没有 LIMIT 定义 | 部分：没有 LIMIT 定义 | 部分：仍没有 LIMIT 定义 |
| 最重要的变更 | 拒答；仅 changed_files | Planner 解析失败 | 已交付，但纯重命名被解释为新增实现，语义失败 |
| 知识库重试窗口 | 正确：12 秒 | Planner 漏契约，失败 | 正确：12 秒 |
| Planner 解析成功 | 4/4（旧五字段） | 1/4（六字段） | 4/4（六字段） |
| Runtime completed | 2/4 | 1/4 | 4/4 |
| **正确完整交付** | **1/4，25%** | **0/4，0%** | **2/4，50%** |

评价为开发者非盲来源核对，不是独立盲审。源码题按运行前固定的 `value * LIMIT`、`LIMIT = 12` 事实要求评价；三版都只读函数体并如实披露常量未取得，所以算部分交付，没有将其当错误事实。重要性题允许有明确限制的相关文件比较，拒绝的是“新增解析实现”这个错误主张，不是因为没有穷举所有文件。

## 实际代码变化

- `core/query_planning/prompt.py`：沿用同一个 Planner 调用，v7 统一六字段说明，明确仓库任务的合法 no_retrieval 字段组合；RAG 也必须带契约。重要性分析与明确全量分析分开。
- `core/engineering_task_contract.py`：增加 `REQUIRED_DIFF_MISSING`；完整状态清单或截断 diff 不能满足真实 diff 要求。
- `core/tool_agent/decision_prompt.py`：把缺口变成当前 Decision 的取证约束；Agent 根据真实清单选择路径和同一 Git scope 下的 diff，取得材料后结束。没有写死路径或 Case ID。
- `core/tool_agent/runtime.py` / `runtime_models.py`：过早 FinalAnswer / 信息不足拒答，在工具可用且还能保留最终 Decision 时，最多获得一次原循环内的恢复机会；重复拒答、缺少工具、预算不足或要求真实测试执行时停止。安全/不支持拒答不重试。
- 复用 `evaluation/task018_e2e/` 原 Launcher、Probe、SQLite 费用闸门；仅扩展四题/三版本调度和诊断字段，没有新增 Runner 类、Planner、Reviewer、Loop、Gold 或预算框架。两个阶段共用累计额度。
- 调整旧 Mock 输入以明确提供恢复后的拒答事件；固定一个旧委托一致性测试的 Fake 时钟，避免 0/1ms 耗时导致无关失败。

业务 Diff 为五文件 **+86/-6**。全部代码/测试相对 Task020、报告加入前为十一文件 **+427/-24**。旧 Router、工具执行语义、5/4/2/60 预算、模型参数及 SDK retries=0 保持不变；没有第二次 Selector 调用。

## 真实轨迹与归因

### Task020 的协议问题

原始 Flash 响应已保留：删除源码使用 `query_type=code_symbol` + `no_retrieval`，重要性使用 `causal` + `no_retrieval`，均违反原字段组合；知识问答只输出旧五字段。不是输出截断、Provider 故障或静默排除失败。Task021 修正 Prompt 说明，未放宽 Parser，也没有新增修复请求。

### Task021 变更分析

实际工具序列为：`changed_files(commit_range)` → `git_diff(src/main.py)` → `git_diff(src/new_parser.py)` → FinalAnswer。E1 为完整状态列表，E2/E3 为完整同范围 diff。四个 Decision，三次工具调用，无工具错误，无解析修复；没有触发早终止恢复分支。因此本次真实结果证明主动补证接线有效；一次恢复的行为仅由离线测试证明，不能声称其真实增益已测得。

模型称 `src/new_parser.py` “引入了新的解析实现”，而 fixture 的双路径 diff 为 **similarity index 100%，仅 rename**。单新路径的真实 git_diff 呈现该路径的新增内容，不能据此断言整个提交新增了函数。轻量校验只确认来源/范围/材料，不验证所有自然语言主张；本次出现一例错误交付，应保留为安全风险。没有现场修 Prompt 后重采样。

旧 case07 的 `INCOMPLETE_SUBQUERY_COVERAGE` 是知识检索分解覆盖不足；没有 `git_diff` 是独立的项目材料不足。Task021 Git-only 契约不把知识子查询变成项目任务要求，并实际取得了 diff，没有关闭 diff 必要性检查。

### 剩余失败

1. 真实 `scale` 回答仍只读取函数定义，未补读同文件 `LIMIT` 常量；结构性函数正文检查不等于完整依赖解释。
2. 重命名分析仍可能把单路径新增表示误解为新功能；这是本轮最应优先处理的问题。
3. 离线诊断中原 Git 工具读取已删除文件 diff 返回 `TOOL_RESULT_INVALID`；本轮不修改工具语义。明确要求全量分析时，四次工具预算可能无法覆盖全部文件，仍拒绝，不能伪造完整性。

## 调用与成本

| 四题累计 | Provider 请求 | Tokens | 软件估算 US$ | Provider 延迟合计 | 产品 execution.elapsed_ms 合计 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Task019 | 13 | 59,075 | 0.0186522 | 14.218s | 15.011s |
| Task020 | 6 | 19,875 | 0.0065574 | 5.854s | 6.067s |
| Task021 | 13 | 69,445 | 0.0222600 | 16.144s | 17.323s |

Task020 三题早失败，所以其低用量不能作为成功执行的开销基准。Task021 相比 Task019 请求总数相同，Tokens +17.6%、估算费用 +19.3%、Provider 延迟 +13.5%；重要性单题由三请求变为五请求，取得两份实际 diff。没有额外 Selector 请求。短样本时延不是性能基准。

本轮合计 **12 次 Agent、32 次 Provider、148,395 tokens、估算 US$0.0474696**。授权上限 84 请求 / 400,000 tokens / US$0.25；无自动重试、额外采样、身份异常、usage 缺失、未知账单或停止条件。所有请求/响应名均 `deepseek-flash`，Thinking disabled、temperature=0。估算按 [官方峰时价格](https://api-docs.deepseek.com/quick_start/pricing/) 0.30/1.20 美元每百万输入/输出 tokens、缓存输入按未命中保守计费；不是实际账单或绝对费用保证。

## 测试、身份与记录

- 最终快速回归：**246 PASS / 0 FAIL / 1 deselected**，未运行那项只能验证冻结 Task019 Live 身份的旧检查。Task021 新增专项 13 项包含在其中。初次回归的计时抖动及 Mock 事件不足已修正，未改产品时钟或预算。
- 专项覆盖主动多文件 diff、一次恢复、重复拒答、预算/工具不可用、错误 E-ID、截断材料、全量范围、现有源码/RAG/Typed/旧 Gate 行为。离线结构反例均阻断，不证明语义幻觉已被消除；真实分析错误已明确登记。
- 控制版本：Task019 `4658857ce7a4b61dce0bdcea98f72cb9a3e5c0d2`；Task020 `0af34f97d3bc0052b99341e00d1741ae2efd41d4`。
- Task021 实现提交 `d185dac`；实际实验冻结 HEAD：`09c4fae90bb5e80e9307286933fc104705b1d314`，业务 SHA-256 `991d4a77a046798d6acca6b59a92e57ae8fe09a390124d3863bbadc7af8173d6`（108 文件）。新分支 `feature/hybrid-evidence-recovery`。
- Task020 旧工作区原始字节指纹 `211987e5d7a38bce9f456258e05bf5bb9b6ac7d1aff61f5de57759fd46bb1889`；新 worktree 的同提交初始指纹因该契约文件 CRLF/LF 不同为 `e0e514…`。已核对 Git blob/换行规范化内容一致，实际控制使用原路径及原指纹，没有修改控制工作区。
- Git fixture BASE `6ba17bcad84c632d72ad62e1a3f8217a0aed05ad`、HEAD `d6b6c100d5e2e441957d834a29a73a8bc4ac1693`；知识语料与 Task018 相同。每次复制为隔离项目/数据库，Agent 自行执行工具，没有预塞 Observation。
- 新结果：`../_task021_hybrid_live_results/task021-controls-20261014-001/` 与 `task021-candidate-20261014-001/`，各自 Manifest、Attempts、Provider Calls、Runtime Events、预算快照、Summary 和 SHA 清单；两组原始 SHA 清单全部通过。新建 `comparison/` 保存实际答案、来源索引和非盲语义核对。B0、B2、Task019、Task020、Candidate 和历史记录均保留。
- candidate 的 Provider Calls 和预算 Summary 包含 controls 的累计记录，按 `seq` 去重共 32 请求；两组 Attempts 分别为八次和四次，未把累计调用重复相加。

结项：保留实验分支供判断，不自动合并、不启动后续实验、不追加付费调用。
