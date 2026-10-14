# Task022：B0 / B2 / Hybrid 真实跨能力对照

**结论：当前完整 Hybrid 不宜替换稳定基线。** 它明确解决了封闭 Git 状态交付，但整体完整正确率低于 B0；Planner/Task Contract 在源码、跨文件与混合任务上带来了新的失败。保留 Typed 的有限事实交付收益，暂缓把当前 Task Contract 作为所有任务的最终裁判。实验分支保留，未合并 main。

84/84 次计划 Agent 运行全部留档；270 次真实请求，1,478,060 tokens，软件估算 US$0.4817769。无未执行题、基础设施失败、身份漂移、未知 usage 或账单状态；所有请求/响应名均 deepseek-flash，temperature=0、Thinking disabled、SDK retries=0。每个 case/版本只运行一次，无评测级重试。Agent 原有的一次 Decision JSON repair 仍计入请求。

## 用户实际交付质量

以下是开发者非盲来源核对，不是独立盲审。评价对象为用户收到的最终答案；被拒候选不计成功。CC=完整正确；UP=有用部分；WD=关键错误或重要结论的实际来源支持不足；ND=无可用交付。正确拒答单独标注，仍保留在 ND 和 28 题分母中。

| 版本 | CC | 完整正确率 | UP | WD | ND | Runtime completed | Planner 阶段失败 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| B0 | 12 | 42.9% | 3 | 2 | 11 | 17 | 0 |
| B2 | 8 | 28.6% | 2 | 2 | 16 | 12 | 0 |
| Hybrid | 10 | 35.7% | 2 | 3 | 13 | 15 | 8 |

Hybrid 相对 B0 的完整正确率 **−7.1 个百分点**，相对 B2 **+7.1 个百分点**。确认的材料充分却被误拦截案例分别为 B0 7、B2 10、Hybrid 3；Hybrid 的减少被 8 个 Planner 失败及其他契约回退抵消。WD 中包含来源支持不足，不能把这些数量全部解释为编造了错误文件路径或数值。Typed 四题没有发现虚构路径、错状态或重命名方向错误。

| 类别（各 4 题） | B0 CC | B2 CC | Hybrid CC |
| --- | ---: | ---: | ---: |
| Git 状态查询 | 0/4 | 0/4 | 4/4 |
| Git 变更分析 | 3/4 | 0/4 | 0/4 |
| 源码定位与解释 | 3/4 | 2/4 | 3/4 |
| 跨文件与测试 | 0/4 | 1/4 | 1/4 |
| RAG 问答 | 2/4 | 1/4 | 1/4 |
| RAG + 代码 | 4/4 | 4/4 | 0/4 |
| 证据不足与拒答 | 0/4 | 0/4 | 1/4 |

## 28 题逐题对照

| Case | 任务 | B0 | B2 | Hybrid | 主要观察 |
| --- | --- | --- | --- | --- | --- |
| t22_gs_01 | 提交范围全部状态 | ND | ND | CC | 旧 Gate 拒绝完整清单；Typed 正确渲染 |
| t22_gs_02 | deleted 文件 | ND | ND | CC | 旧 Gate 拒绝；Typed 精确过滤 |
| t22_gs_03 | rename 新旧路径 | ND | ND | CC | Typed 重命名方向正确 |
| t22_gs_04 | untracked 文件 | ND | ND | CC | Typed 正确区分未跟踪状态 |
| t22_ga_01 | 重要性与证据范围 | CC | ND | WD | B0 有界分析；Hybrid 先外推未检查文件的性质 |
| t22_ga_02 | main.py 数值变更 | CC | ND | ND | Hybrid Planner 字段组合无效 |
| t22_ga_03 | 文档与源码 diff | CC | ND | ND | Hybrid 在 change_analysis 中误填 added 状态 |
| t22_ga_04 | 完整分析全部变更 | WD | ND | ND | 完整范围未取全；B0 仍推断测试已同步 |
| t22_src_01 | scale 文件/行号定位 | ND | ND | ND | B0/B2 引用被拦；Hybrid Planner 无效 |
| t22_src_02 | scale 实现与常量 | CC | CC | CC | 三版都取得函数与 LIMIT=12 |
| t22_src_03 | parse 字符串处理 | CC | CC | CC | 三版核心实现解释正确 |
| t22_src_04 | scale(3) 真实数值 | CC | UP | CC | B2 未取得常量；其他两版确认 36 |
| t22_xt_01 | 源码与测试静态一致性 | UP | CC | ND | B0 缺常量；B2 完成；Hybrid 强加 diff/两代码路径 |
| t22_xt_02 | 候选测试定位 | ND | ND | CC | Hybrid 交付候选，未声称覆盖或执行 |
| t22_xt_03 | 重命名前后内容对比 | UP | ND | ND | B0 有界部分；B2 旧路径 diff 无效；Hybrid 解析失败 |
| t22_xt_04 | 测试全文及证明边界 | ND | ND | ND | 旧正文类型错配；Hybrid Planner 失败 |
| t22_rag_01 | 语料/索引版本与回归 | CC | CC | CC | 三版版本身份与回归说明有实际来源 |
| t22_rag_02 | 证据支持与验证能力 | WD | WD | WD | 共同夸大 verification 的证明范围；术语有歧义 |
| t22_rag_03 | 文档增量更新 | CC | WD | WD | B0 命中步骤正文；B2/Hybrid 引自检问题来支撑步骤 |
| t22_rag_04 | Mock/Stub 与覆盖率 | UP | UP | UP | 检索未取到覆盖率定义；Hybrid 用非资料补充 |
| t22_mix_01 | parse + Function Calling | CC | CC | ND | Hybrid 把 Function Calling 误当函数 Calling 目标 |
| t22_mix_02 | 重试窗口与 LIMIT 独立性 | CC | CC | UP | Hybrid 未补读 LIMIT，但未伪造关联 |
| t22_mix_03 | 测试断言意图与执行边界 | CC | CC | ND | Hybrid 将意图/边界分析错判为 test_execution |
| t22_mix_04 | 文档/源码/知识来源身份 | CC | CC | ND | Hybrid 把 doc+code 要求变成两个代码路径 |
| t22_ev_01 | 不存在的源码 | ND | ND | ND | 旧版查得文件不存在；Hybrid 未进入工具循环 |
| t22_ev_02 | 实际执行 pytest | ND | ND | ND | 三版均保留测试工具能力边界 |
| t22_ev_03 | 生产重试配置的证据边界 | ND | ND | CC | Hybrid 交付有来源的不可确认说明 |
| t22_ev_04 | 确认 pytest 已全部通过 | ND | ND | ND | 旧版拒答；Hybrid Planner 空 Git refs 无效 |

## 多工具和多来源能力

Git 分析、跨文件/测试、RAG+代码这 12 个预先固定的复杂任务，完整正确分别为 **B0 7/12、B2 5/12、Hybrid 1/12**。不能据本轮结果宣称 Hybrid 的多工具任务能力整体提升。全 28 题中，两次以上真实 ToolAgent 工具调用的运行数为 9/10/6，工具调用总量为 34/37/25；Hybrid 的低数量主要受 Planner 早失败影响。知识检索仍走原产品 Planner 后检索链，不是预塞 Observation。

- Hybrid 在 t22_ga_01 自主执行 changed_files → git_diff(main.py) → git_diff(new_parser.py)，纯重命名呈现已正确；但对未检查变更的概括过宽，仍不计 CC。
- t22_src_02/04 实际补读 LIMIT，交付正确数值；t22_mix_02 仍只取得函数体，说明 Prompt 小修补不能保证依赖完整性。
- t22_xt_01 真实取得源码、测试与 LIMIT，却因错误 change_analysis/diff 义务及两 project_code 路径要求拒答。t22_mix_04 的 doc/code/knowledge 全部取得，也被混合类型计数阻断。
- t22_ga_04 的全范围 diff 未取全；Hybrid 保留完整性阻断，没有为了全题完成而扩大 5/4/2/60 预算。

## 开销

| 版本（28 次） | Provider 请求 | 平均请求 | Tokens | 估算 US$ | 平均产品耗时 | Provider 延迟合计 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| B0 | 94 | 3.36 | 493,112 | 0.1613202 | 5.384s | 143.881s |
| B2 | 99 | 3.54 | 545,043 | 0.1766880 | 5.428s | 144.600s |
| Hybrid | 77 | 2.75 | 439,905 | 0.1437687 | 4.475s | 120.021s |

Hybrid 总开销较低，不能直接视为效率提升：8 题在首个 Planner 请求后失败。三版均 Runtime completed 的同一组 8 题，各为 24 请求；Tokens 分别 120,175 / 123,130 / 150,380，费用 $0.0405120 / $0.0407775 / $0.0496689，产品耗时合计 45.144 / 42.826 / 46.064 秒。Hybrid 在这组相同已交付题上的 Token 比 B0/B2 多约 25.1%/22.1%，且其中仍有部分/错误交付。

无独立 Selector 请求：Provider roles 为 Planner、Decision、原有 Decision repair。三版 repair 次数为 2/3/3。费用按[官方峰时价格](https://api-docs.deepseek.com/quick_start/pricing/)输入 $0.30/M、输出 $1.20/M 保守估算，缓存输入按未命中计费；这是软件估算，不是服务商账单保证。

## 各版最主要失败

**B0**：① status/locator/candidate 没有可用正式 E-ID，旧引用 Gate 拒绝；② 源码依赖或多文件材料未取全，能交付的回答仍有遗漏/外推；③ BM25 命中自检问题而非解释正文，引用存在但不能支持能力结论。

**B2**：① 完整工具事实已取得，但新增自然语言 Binding 的格式/批次约束仍拒绝清单和 diff 回答；② 工具策略未补读常量、旧路径删除 diff 触发 TOOL_RESULT_INVALID；③ 与 B0 相同的知识片段覆盖和引用支持问题。

**Hybrid**：① 8 个 Planner/Contract 首阶段失败；② 三个任务的错误义务导致材料齐全仍拒答；③ 轻量来源校验无法阻止范围外概括与引用自检问题来支持解释性结论。

Planner 实际响应的离线解析确认：6 个失败含 no_retrieval 与 causal/code_symbol/comparison/troubleshooting 的非法组合；t22_ga_03 在 change_analysis 中填 status=added；t22_mix_01 被 `function Calling` 的显式符号正则误读为遗漏 Calling。t22_src_01 还把定位任务填成携带函数符号的 file_status；t22_ev_04 的 commit_range refs 为 null。源码位置：core/query_planning/models.py:412、planner.py:269；core/engineering_task_contract.py:58、98、113。

契约误拦截来自实际字段与确定性检查：t22_xt_01 requires_diff=true（material_error:212）且 source/test 两路径计为两份代码；t22_mix_03 operation=test_execution（没有执行工具，不可满足）；t22_mix_04 object_kind=knowledge + requires_source_body，把 doc+code 两路径变成两份 project_code（to_requirement:168）。这些没有在测量中修复。

RAG 质量限制：t22_rag_02 的 verification 用词有歧义，回答也未读取任何具体 Verifier 源码；该题用于核查回答表述与引用支持，不能据此证明某个 Verifier 的真实语义能力。t22_rag_03 中 B2/Hybrid 的更新原则与完整语料相符，但实际 E1 仅是自检问题；保守结果依据冻结的“重要结论必须有实际来源支持”口径标 WD，CSV 已明确这一性质。t22_rag_04 的覆盖率定义存在于原文，检索却没取得，不能声称整个语料没有定义。

## 实验身份与代码

| 版本 | 实际业务 Commit | 实际业务 SHA-256 |
| --- | --- | --- |
| B0 | `f3c9e28aec8b29ccfcad9476ea88871aacbefa06` | `df1fca48d9f4db385c1726543c34b9c32188f5a92091d527b459213d34698220` |
| B2 | `de0ca632c4a8a0b67d6f6bb1c2c6eb55d741d131` | `2101868665a1c8f3732d66517b63bc1142a16968941368854be8ebd96201f028` |
| Hybrid | `afa384668e00401385b5cc2084d4e515b73474da` | `2b52c20a5ee8af957aaab317eafda8232f98d2bf1d531b84cd01395c95cdfa8d` |

Hybrid 在 Task021 HEAD 5646e2c 上仅作了授权的小修复：git_diff 对可信 rename 的新旧路径一起读取，避免把纯 rename 呈现为新增实现；删除 diff 的新侧行范围下限修复；Decision 提示明确补读直接引用的同文件常量。业务两文件 +22/−4。测试和既有 Runner/Probe 的矩阵/诊断适配另计；冻结提交总计五文件 +354/−32。Router、Loop、Schema 和预算未改，未建立新 Planner/Reviewer/Runner。收益不能被归因为单一机制的纯消融。

共同 Git BASE `6ba17bcad84c632d72ad62e1a3f8217a0aed05ad`，HEAD `d6b6c100d5e2e441957d834a29a73a8bc4ac1693`。每次 Runtime 在新临时副本上自行调用工具；没有注入 Observation。三版登记工具集合与 5 Decision / 4 Tool Calls / 2 Errors / 60s 预算一致。

本轮知识 fixture 为既有本地 Markdown 文档的隔离副本：文档处理、高级 RAG、单元测试、Function Calling，加 Task018 重试 fixture，共 5 文档、27 chunks。所有 84 次使用同一个冻结数据库副本，DB SHA `5ae658d4d2448eabb90dc8ee263e584cfd9bba4660ce4e2908b83bba50d89e0a`。原语料和历史数据库未改；Library identity.verified 仍为 false，源文件/DB SHA 核对不等同于已验证的生产语料身份。

28 题是在 Dev/Validation、已有 integration_v7 题型和 Task018–021 fixture 上固定的有界适配题。没有宣称它们是独立盲测或覆盖完整生产分布，也没有与历史 Smoke/72题成绩混算。固定意图/事实口径仅写入父进程 Manifest，用于事后核查，不进入模型输入。

必要离线验证：Git 工具 17 PASS / 1 SKIP（本机无法创建 symlink）；预算/usage/二进制 JSON 边界 4 PASS；三版 Fake 源码 Runtime 接线各完成。最初默认 pytest 临时目录 ACL 导致 18 个 setup 错误，改用新的隔离 basetemp 后通过；没有据此改业务断言。Fake 不计真实语义成绩。

## 产物与决策

- `TASK022_ACTUAL_ANSWERS_AND_SOURCES.md`：84 条实际交付、被拒候选、真实工具序列和 E-ID 来源索引。
- `evaluation/task018_e2e/task022_semantic_review.csv`：逐条质量、原因、误拒答/合理拒答、调用和成本。
- `evaluation/task018_e2e/task022_artifacts_sha256.json`：原始七份产物的身份索引；原始 SHA 全部通过。
- 原始记录：`D:\学习\rag实战项目\_task022_cross_capability_results\task022-cross-capability-20261014-001`（Manifest、Attempts、Runtime Events、Provider Calls、SQLite 预算、Summary、SHA 清单）。

建议保留封闭状态 Typed 交付和只读来源约束；**暂不采用完整 Hybrid 替换旧 Finalization/需求裁判**。它比 B2 多完成两题，但比 B0 少两题，复杂任务与混合能力明显回退，来源外主张也未消失。最优先的问题是 Planner/Task Contract 的协议和义务转换可靠性；本轮只记录，不继续追加模块、改失败题或付费补跑。

分支：[experiment/task022-cross-capability](https://github.com/wgqa/my_agent/tree/experiment/task022-cross-capability)。实际实验冻结 Commit `afa384668e00401385b5cc2084d4e515b73474da`；交付报告提交见分支 HEAD。本轮结束。
