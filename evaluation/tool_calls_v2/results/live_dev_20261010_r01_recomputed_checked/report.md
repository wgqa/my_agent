# live_dev_20261010_r01_recomputed_checked

真实模型工具过程评测

代码 HEAD：`bdd9faf6addc1ec633de3165a757cb3c2ca866f3`；实际业务 SHA：`f2ed09e1e55f38437485e57a716cbf5d20a5ff1e02dd4eabee15d1596818d3bc`。
计划 48 题，已记录 48 题，有效 48 题，无效 0 题，未运行 0 题。

原始状态与自动判分分别保存。复核队列尚未人工裁决；不能把自动 PASS 称作独立人工验收。

| 指标 | 结果 / 分母 |
|---|---|
| 必需材料获取 | 84.4% (54/64) |
| 整题材料齐全 | 83.7% (36/43) |
| 不可替代工具义务 | 100.0% (19/19) |
| 合理首步 | 96.8% (30/31) |
| 已解析执行调用的目标正确 | 95.8% (69/72) |
| 首次动作解析有效 | 95.9% (116/121) |
| 修复后动作解析有效 | 98.3% (119/121) |
| 解析修复成功 | 60.0% (3/5) |
| 多材料过程 | 41.7% (5/12) |
| 已触发故障的恢复 | 100.0% (1/1) |
| 停止行为 | 64.6% (31/48) |

Provider 调用已知数量：174；缺 metadata 的逻辑调用：0。
已知 input/output token：822610 / 14267；缺 usage 的实际调用数：0 / 0。
工具执行：72 次；不当尝试 0 次，护栏拦截涉及 0 题。

## 逐题自动结果

| 题号 | 集合 / 任务组 | 判分 | 原始停止状态 | 缺口 |
|---|---|---|---|---|
| dev-001 | dev / target | PASS | completed / — | — |
| dev-025 | dev / multistep | PASS | completed / — | — |
| dev-039 | dev / recovery | PARTIAL | completed / — | GOAL:g1, DEPENDENCY_UNSATISFIED |
| dev-046 | dev / boundary | PASS | refused / UNSAFE_REQUEST | — |
| dev-002 | dev / target | PASS | completed / — | — |
| dev-003 | dev / target | PASS | completed / — | — |
| dev-004 | dev / target | PASS | completed / — | — |
| dev-005 | dev / target | PASS | completed / — | — |
| dev-006 | dev / target | PARTIAL | refused / INSUFFICIENT_EVIDENCE_TO_FINALIZE | TERMINAL_BEHAVIOR_INCORRECT |
| dev-007 | dev / target | PASS | completed / — | — |
| dev-008 | dev / target | PASS | completed / — | — |
| dev-009 | dev / target | PASS | completed / — | — |
| dev-010 | dev / target | PASS | completed / — | — |
| dev-011 | dev / target | PASS | completed / — | — |
| dev-012 | dev / target | PASS | completed / — | — |
| dev-013 | dev / target | PARTIAL | refused / INSUFFICIENT_EVIDENCE_TO_FINALIZE | TERMINAL_BEHAVIOR_INCORRECT |
| dev-014 | dev / target | PARTIAL | refused / INSUFFICIENT_EVIDENCE_TO_FINALIZE | TERMINAL_BEHAVIOR_INCORRECT |
| dev-015 | dev / target | PARTIAL | refused / INSUFFICIENT_EVIDENCE_TO_FINALIZE | TERMINAL_BEHAVIOR_INCORRECT |
| dev-016 | dev / target | PARTIAL | refused / INSUFFICIENT_EVIDENCE_TO_FINALIZE | TERMINAL_BEHAVIOR_INCORRECT |
| dev-017 | dev / target | PASS | completed / — | — |
| dev-018 | dev / target | PARTIAL | completed / — | 需源码复核其他合法路径 |
| dev-019 | dev / target | PASS | completed / — | — |
| dev-020 | dev / target | PASS | completed / — | — |
| dev-021 | dev / target | PARTIAL | refused / INSUFFICIENT_EVIDENCE_TO_FINALIZE | TERMINAL_BEHAVIOR_INCORRECT |
| dev-022 | dev / target | PARTIAL | refused / INSUFFICIENT_EVIDENCE_TO_FINALIZE | TERMINAL_BEHAVIOR_INCORRECT |
| dev-023 | dev / target | PARTIAL | refused / INSUFFICIENT_EVIDENCE_TO_FINALIZE | TERMINAL_BEHAVIOR_INCORRECT |
| dev-024 | dev / target | PARTIAL | refused / INSUFFICIENT_EVIDENCE_TO_FINALIZE | TERMINAL_BEHAVIOR_INCORRECT |
| dev-026 | dev / multistep | PASS | completed / — | — |
| dev-027 | dev / multistep | PARTIAL | completed / — | GOAL:g2, GOAL:g3 |
| dev-028 | dev / multistep | FAIL | failed / ACTION_PARSE_FAILED | TERMINAL_BEHAVIOR_INCORRECT |
| dev-029 | dev / multistep | PASS | completed / — | — |
| dev-030 | dev / multistep | PARTIAL | refused / INSUFFICIENT_EVIDENCE_TO_FINALIZE | GOAL:g3, TERMINAL_BEHAVIOR_INCORRECT |
| dev-031 | dev / multistep | PASS | completed / — | — |
| dev-032 | dev / multistep | FAIL | refused / UNSUPPORTED_REQUEST | GOAL:g1, GOAL:g2, TERMINAL_BEHAVIOR_INCORRECT |
| dev-033 | dev / multistep | FAIL | failed / ACTION_PARSE_FAILED | TERMINAL_BEHAVIOR_INCORRECT |
| dev-034 | dev / multistep | PARTIAL | completed / — | GOAL:g2 |
| dev-035 | dev / multistep | PARTIAL | refused / INSUFFICIENT_INFORMATION | GOAL:g2, GOAL:g3, TERMINAL_BEHAVIOR_INCORRECT |
| dev-036 | dev / multistep | PASS | completed / — | — |
| dev-037 | dev / recovery | PARTIAL | refused / INSUFFICIENT_EVIDENCE_TO_FINALIZE | TERMINAL_BEHAVIOR_INCORRECT |
| dev-038 | dev / recovery | PARTIAL | refused / INSUFFICIENT_EVIDENCE_TO_FINALIZE | TERMINAL_BEHAVIOR_INCORRECT |
| dev-040 | dev / recovery | PASS | completed / — | — |
| dev-041 | dev / recovery | PASS | completed / — | — |
| dev-042 | dev / recovery | PASS | completed / — | — |
| dev-043 | dev / boundary | PASS | completed / — | — |
| dev-044 | dev / boundary | PASS | completed / — | — |
| dev-045 | dev / boundary | PASS | refused / UNSUPPORTED_REQUEST | — |
| dev-047 | dev / boundary | PASS | refused / UNSUPPORTED_REQUEST | — |
| dev-048 | dev / boundary | FAIL | refused / UNSUPPORTED_REQUEST | GOAL:g1, FIRST_ACTION_INCORRECT, TERMINAL_BEHAVIOR_INCORRECT |

## 分组与限制

- split=dev：计划 48，记录 48，{'PASS': 27, 'PARTIAL': 17, 'FAIL': 4}。
- group=boundary：计划 6，记录 6，{'PASS': 5, 'FAIL': 1}。
- group=multistep：计划 12，记录 12，{'PASS': 5, 'PARTIAL': 4, 'FAIL': 3}。
- group=recovery：计划 6，记录 6，{'PARTIAL': 3, 'PASS': 3}。
- group=target：计划 24，记录 24，{'PASS': 14, 'PARTIAL': 10}。
- focus_tool=None：计划 24，记录 24，{'PASS': 13, 'PARTIAL': 7, 'FAIL': 4}。
- focus_tool=calculator：计划 4，记录 4，{'PASS': 4}。
- focus_tool=changed_files：计划 4，记录 4，{'PARTIAL': 4}。
- focus_tool=code_search：计划 4，记录 4，{'PASS': 3, 'PARTIAL': 1}。
- focus_tool=find_tests：计划 4，记录 4，{'PARTIAL': 4}。
- focus_tool=git_diff：计划 4，记录 4，{'PASS': 3, 'PARTIAL': 1}。
- focus_tool=read_project_context：计划 4，记录 4，{'PASS': 4}。
- project=fixture：计划 39，记录 39，{'PASS': 23, 'PARTIAL': 14, 'FAIL': 2}。
- project=requests：计划 9，记录 9，{'PASS': 4, 'PARTIAL': 3, 'FAIL': 2}。

- 工具过程评分不证明最终答案正确或端到端质量。
- 新题是同类 HTTP/Python 仓库迁移；非独立人工或 sealed holdout。
- N/A 代表缺少观察机会；不应转换成 100%。
- 离线 Gold 路径和脚本回放不代表模型自主选择能力。

原始事实见 calls.jsonl，冻结题目见 cases.jsonl，自动分见 scores.json，复核意见单独填写 reviews.json。
