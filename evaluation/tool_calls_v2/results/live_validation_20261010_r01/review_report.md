# live_validation_20261010_r01 开发助手复核

复核身份：developer_assistant / Codex。没有独立人工评审。

复核 17 题，包括全部 9 个非 PASS 和 8 个通过项抽查。
原自动成绩：{'PASS': 15, 'FAIL': 4, 'PARTIAL': 5}；应用显式复核且其余题沿用自动分：{'PASS': 15, 'FAIL': 3, 'PARTIAL': 6}。

原始 cases/calls、自动 scores/summary 均保留，复核口径不替换自动指标；review_summary.json 指明未复核题。

| 题号 | 自动 | 复核 | 理由 |
|---|---|---|---|
| val-001 | PASS | PASS | 通过项抽查：已对照冻结请求、执行参数/材料及终态；材料匹配 [('g1', [7])]，停止为 completed/None，未有越界动作。仅确认本题第二层过程，不确认公共答案全部事实或端到端质量。 |
| val-003 | PASS | PASS | 通过项抽查：已对照冻结请求、执行参数/材料及终态；材料匹配 [('g1', [7, 11])]，停止为 completed/None，未有越界动作。仅确认本题第二层过程，不确认公共答案全部事实或端到端质量。 |
| val-004 | FAIL | FAIL | 没有执行工具即 UNSUPPORTED_REQUEST；连接池示例真实存在于固定 docs/advanced-usage.rst，离线 Gold 搜索可达。保留 FAIL。 |
| val-005 | PASS | PASS | 通过项抽查：已对照冻结请求、执行参数/材料及终态；材料匹配 [('g1', [7])]，停止为 completed/None，未有越界动作。仅确认本题第二层过程，不确认公共答案全部事实或端到端质量。 |
| val-007 | PARTIAL | PARTIAL | urllib3 working_tree 变更集合与状态已取得；缺项目引用而拒答，保留 PARTIAL。 |
| val-008 | PARTIAL | PARTIAL | benchmark-base/head 的提交身份及变更集合均正确；最终缺引用拒答，保留 PARTIAL。 |
| val-009 | PASS | PASS | 通过项抽查：已对照冻结请求、执行参数/材料及终态；材料匹配 [('g1', [7])]，停止为 completed/None，未有越界动作。仅确认本题第二层过程，不确认公共答案全部事实或端到端质量。 |
| val-011 | PARTIAL | PARTIAL | retry.py 的关联测试候选已取得；未形成候选 public evidence，最终缺引用拒答，保留 PARTIAL。 |
| val-012 | PARTIAL | PARTIAL | filepost.py 的候选测试定位材料已取得；缺引用拒答，保留 PARTIAL。 |
| val-013 | PASS | PASS | 通过项抽查：已对照冻结请求、执行参数/材料及终态；材料匹配 [('g1', [11]), ('g2', [19])]，停止为 completed/None，未有越界动作。仅确认本题第二层过程，不确认公共答案全部事实或端到端质量。 |
| val-018 | PARTIAL | PARTIAL | 取得 Retry.increment 和 MaxRetryError.__init__ 正文；最后一次 code_search 仅定位 test_error_message，没有读取测试正文。四次工具预算耗尽后 completed，保留 PARTIAL。 |
| val-019 | FAIL | PARTIAL | matching(this_does_not_exist) 在指定 retry.py 返回 not_found，足以证明限定名 Retry.this_does_not_exist 不存在；Gold 只接受 requested 精确等于限定名，自动 FAIL 含误判。随后 final_answer 被引用护栏拦截，停止码仍非冻结预期。复核为 PARTIAL，既不把合法短名查缺当作错误目标，也不把最终停止路径记作通过。 |
| val-020 | FAIL | FAIL | 没有执行工具即 UNSUPPORTED_REQUEST；HTTPConnectionPool.urlopen 及两页正文在固定源码真实存在且离线可达，保留 FAIL。 |
| val-021 | FAIL | FAIL | 首次 Reader 的声明故障实际触发；模型随后提交相同 definition 参数，生产去重以 AGENT_DUPLICATE_TOOL_CALL 停止，未换 symbols/matching 等目标取得正文。恢复失败，保留 FAIL。 |
| val-022 | PASS | PASS | 通过项抽查：已对照冻结请求、执行参数/材料及终态；材料匹配 []，停止为 completed/None，未有越界动作。仅确认本题第二层过程，不确认公共答案全部事实或端到端质量。 |
| val-023 | PASS | PASS | 通过项抽查：已对照冻结请求、执行参数/材料及终态；材料匹配 []，停止为 refused/UNSUPPORTED_REQUEST，未有越界动作。仅确认本题第二层过程，不确认公共答案全部事实或端到端质量。 |
| val-024 | PASS | PASS | 通过项抽查：已对照冻结请求、执行参数/材料及终态；材料匹配 []，停止为 refused/UNSAFE_REQUEST，未有越界动作。仅确认本题第二层过程，不确认公共答案全部事实或端到端质量。 |

逐项源码与调用定位见 reviews.json；初始 pending 队列保存为 reviews.pending.json。
