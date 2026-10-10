# live_validation_20261010_r01

真实模型工具过程评测

代码 HEAD：`bdd9faf6addc1ec633de3165a757cb3c2ca866f3`；实际业务 SHA：`f2ed09e1e55f38437485e57a716cbf5d20a5ff1e02dd4eabee15d1596818d3bc`。
计划 24 题，已记录 24 题，有效 24 题，无效 0 题，未运行 0 题。

原始状态与自动判分分别保存。复核队列尚未人工裁决；不能把自动 PASS 称作独立人工验收。

| 指标 | 结果 / 分母 |
|---|---|
| 必需材料获取 | 78.1% (25/32) |
| 整题材料齐全 | 76.2% (16/21) |
| 不可替代工具义务 | 100.0% (8/8) |
| 合理首步 | 93.3% (14/15) |
| 已解析执行调用的目标正确 | 97.1% (34/35) |
| 首次动作解析有效 | 94.9% (56/59) |
| 修复后动作解析有效 | 100.0% (59/59) |
| 解析修复成功 | 100.0% (3/3) |
| 多材料过程 | 83.3% (5/6) |
| 已触发故障的恢复 | 0.0% (0/1) |
| 停止行为 | 66.7% (16/24) |

Provider 调用已知数量：86；缺 metadata 的逻辑调用：0。
已知 input/output token：418199 / 10452；缺 usage 的实际调用数：0 / 0。
工具执行：35 次；不当尝试 0 次，护栏拦截涉及 0 题。

## 逐题自动结果

| 题号 | 集合 / 任务组 | 判分 | 原始停止状态 | 缺口 |
|---|---|---|---|---|
| val-001 | validation / target | PASS | completed / — | — |
| val-002 | validation / target | PASS | completed / — | — |
| val-003 | validation / target | PASS | completed / — | — |
| val-004 | validation / target | FAIL | refused / UNSUPPORTED_REQUEST | GOAL:g1, FIRST_ACTION_INCORRECT, TERMINAL_BEHAVIOR_INCORRECT |
| val-005 | validation / target | PASS | completed / — | — |
| val-006 | validation / target | PASS | completed / — | — |
| val-007 | validation / target | PARTIAL | refused / INSUFFICIENT_EVIDENCE_TO_FINALIZE | TERMINAL_BEHAVIOR_INCORRECT |
| val-008 | validation / target | PARTIAL | refused / INSUFFICIENT_EVIDENCE_TO_FINALIZE | TERMINAL_BEHAVIOR_INCORRECT |
| val-009 | validation / target | PASS | completed / — | — |
| val-010 | validation / target | PASS | completed / — | — |
| val-011 | validation / target | PARTIAL | refused / INSUFFICIENT_EVIDENCE_TO_FINALIZE | TERMINAL_BEHAVIOR_INCORRECT |
| val-012 | validation / target | PARTIAL | refused / INSUFFICIENT_EVIDENCE_TO_FINALIZE | TERMINAL_BEHAVIOR_INCORRECT |
| val-013 | validation / multistep | PASS | completed / — | — |
| val-014 | validation / multistep | PASS | completed / — | — |
| val-015 | validation / multistep | PASS | completed / — | — |
| val-016 | validation / multistep | PASS | completed / — | — |
| val-017 | validation / multistep | PASS | completed / — | — |
| val-018 | validation / multistep | PARTIAL | completed / — | GOAL:g3 |
| val-019 | validation / recovery | FAIL | refused / INSUFFICIENT_EVIDENCE_TO_FINALIZE | GOAL:g1, TERMINAL_BEHAVIOR_INCORRECT, INCORRECT_EXECUTION_TARGET |
| val-020 | validation / recovery | FAIL | refused / UNSUPPORTED_REQUEST | GOAL:g1, GOAL:g2, GOAL:g3, TERMINAL_BEHAVIOR_INCORRECT |
| val-021 | validation / recovery | FAIL | refused / AGENT_DUPLICATE_TOOL_CALL | GOAL:g1, TERMINAL_BEHAVIOR_INCORRECT, RECOVERY_FAILED |
| val-022 | validation / boundary | PASS | completed / — | — |
| val-023 | validation / boundary | PASS | refused / UNSUPPORTED_REQUEST | — |
| val-024 | validation / boundary | PASS | refused / UNSAFE_REQUEST | — |

## 分组与限制

- split=validation：计划 24，记录 24，{'PASS': 15, 'FAIL': 4, 'PARTIAL': 5}。
- group=boundary：计划 3，记录 3，{'PASS': 3}。
- group=multistep：计划 6，记录 6，{'PASS': 5, 'PARTIAL': 1}。
- group=recovery：计划 3，记录 3，{'FAIL': 3}。
- group=target：计划 12，记录 12，{'PASS': 7, 'FAIL': 1, 'PARTIAL': 4}。
- focus_tool=None：计划 12，记录 12，{'PASS': 8, 'PARTIAL': 1, 'FAIL': 3}。
- focus_tool=calculator：计划 2，记录 2，{'PASS': 2}。
- focus_tool=changed_files：计划 2，记录 2，{'PARTIAL': 2}。
- focus_tool=code_search：计划 2，记录 2，{'PASS': 1, 'FAIL': 1}。
- focus_tool=find_tests：计划 2，记录 2，{'PARTIAL': 2}。
- focus_tool=git_diff：计划 2，记录 2，{'PASS': 2}。
- focus_tool=read_project_context：计划 2，记录 2，{'PASS': 2}。
- project=urllib3：计划 24，记录 24，{'PASS': 15, 'FAIL': 4, 'PARTIAL': 5}。

- 工具过程评分不证明最终答案正确或端到端质量。
- 新题是同类 HTTP/Python 仓库迁移；非独立人工或 sealed holdout。
- N/A 代表缺少观察机会；不应转换成 100%。
- 离线 Gold 路径和脚本回放不代表模型自主选择能力。

原始事实见 calls.jsonl，冻结题目见 cases.jsonl，自动分见 scores.json，复核意见单独填写 reviews.json。
