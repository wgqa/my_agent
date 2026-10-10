# offline_facade_20261009_final

当前产品装配脚本回放（无模型）

代码 HEAD：`bdd9faf6addc1ec633de3165a757cb3c2ca866f3`；实际业务 SHA：`6a679bd9475e3f2f9ecfb8c9ef2b818ae641382de042e2fe0c1850de51e6037c`。
计划 72 题，已记录 72 题，有效 72 题，无效 0 题，未运行 0 题。

原始状态与自动判分分别保存。复核队列尚未人工裁决；不能把自动 PASS 称作独立人工验收。

| 指标 | 结果 / 分母 |
|---|---|
| 必需材料获取 | 100.0% (96/96) |
| 整题材料齐全 | 100.0% (64/64) |
| 不可替代工具义务 | 100.0% (27/27) |
| 合理首步 | 100.0% (46/46) |
| 已解析执行调用的目标正确 | 100.0% (94/94) |
| 首次动作解析有效 | N/A (0 个观察机会) |
| 修复后动作解析有效 | N/A (0 个观察机会) |
| 解析修复成功 | N/A (0 个观察机会) |
| 多材料过程 | 100.0% (18/18) |
| 已触发故障的恢复 | 100.0% (3/3) |
| 停止行为 | 98.6% (71/72) |

Provider 调用已知数量：0；缺 metadata 的逻辑调用：239。
已知 input/output token：None / None；缺 usage 的实际调用数：0 / 0。
工具执行：94 次；不当尝试 0 次，护栏拦截涉及 0 题。

## 逐题自动结果

| 题号 | 集合 / 任务组 | 判分 | 原始停止状态 | 缺口 |
|---|---|---|---|---|
| dev-001 | dev / target | PASS | completed / — | — |
| dev-002 | dev / target | PASS | completed / — | — |
| dev-003 | dev / target | PASS | completed / — | — |
| dev-004 | dev / target | PASS | completed / — | — |
| dev-005 | dev / target | PASS | completed / — | — |
| dev-006 | dev / target | PASS | completed / — | — |
| dev-007 | dev / target | PASS | completed / — | — |
| dev-008 | dev / target | PASS | completed / — | — |
| dev-009 | dev / target | PASS | completed / — | — |
| dev-010 | dev / target | PASS | completed / — | — |
| dev-011 | dev / target | PASS | completed / — | — |
| dev-012 | dev / target | PASS | completed / — | — |
| dev-013 | dev / target | PASS | completed / — | — |
| dev-014 | dev / target | PASS | completed / — | — |
| dev-015 | dev / target | PARTIAL | refused / INSUFFICIENT_EVIDENCE_TO_FINALIZE | TERMINAL_BEHAVIOR_INCORRECT |
| dev-016 | dev / target | PASS | completed / — | — |
| dev-017 | dev / target | PASS | completed / — | — |
| dev-018 | dev / target | PASS | completed / — | — |
| dev-019 | dev / target | PASS | completed / — | — |
| dev-020 | dev / target | PASS | completed / — | — |
| dev-021 | dev / target | PASS | completed / — | — |
| dev-022 | dev / target | PASS | completed / — | — |
| dev-023 | dev / target | PASS | completed / — | — |
| dev-024 | dev / target | PASS | completed / — | — |
| dev-025 | dev / multistep | PASS | completed / — | — |
| dev-026 | dev / multistep | PASS | completed / — | — |
| dev-027 | dev / multistep | PASS | completed / — | — |
| dev-028 | dev / multistep | PASS | completed / — | — |
| dev-029 | dev / multistep | PASS | completed / — | — |
| dev-030 | dev / multistep | PASS | completed / — | — |
| dev-031 | dev / multistep | PASS | completed / — | — |
| dev-032 | dev / multistep | PASS | completed / — | — |
| dev-033 | dev / multistep | PASS | completed / — | — |
| dev-034 | dev / multistep | PASS | completed / — | — |
| dev-035 | dev / multistep | PASS | completed / — | — |
| dev-036 | dev / multistep | PASS | completed / — | — |
| dev-037 | dev / recovery | PASS | refused / INSUFFICIENT_INFORMATION | — |
| dev-038 | dev / recovery | PASS | refused / INSUFFICIENT_INFORMATION | — |
| dev-039 | dev / recovery | PASS | completed / — | — |
| dev-040 | dev / recovery | PASS | completed / — | — |
| dev-041 | dev / recovery | PASS | completed / — | — |
| dev-042 | dev / recovery | PASS | completed / — | — |
| dev-043 | dev / boundary | PASS | completed / — | — |
| dev-044 | dev / boundary | PASS | completed / — | — |
| dev-045 | dev / boundary | PASS | refused / UNSUPPORTED_REQUEST | — |
| dev-046 | dev / boundary | PASS | refused / UNSAFE_REQUEST | — |
| dev-047 | dev / boundary | PASS | refused / UNSUPPORTED_REQUEST | — |
| dev-048 | dev / boundary | PASS | completed / — | — |
| val-001 | validation / target | PASS | completed / — | — |
| val-002 | validation / target | PASS | completed / — | — |
| val-003 | validation / target | PASS | completed / — | — |
| val-004 | validation / target | PASS | completed / — | — |
| val-005 | validation / target | PASS | completed / — | — |
| val-006 | validation / target | PASS | completed / — | — |
| val-007 | validation / target | PASS | completed / — | — |
| val-008 | validation / target | PASS | completed / — | — |
| val-009 | validation / target | PASS | completed / — | — |
| val-010 | validation / target | PASS | completed / — | — |
| val-011 | validation / target | PASS | completed / — | — |
| val-012 | validation / target | PASS | completed / — | — |
| val-013 | validation / multistep | PASS | completed / — | — |
| val-014 | validation / multistep | PASS | completed / — | — |
| val-015 | validation / multistep | PASS | completed / — | — |
| val-016 | validation / multistep | PASS | completed / — | — |
| val-017 | validation / multistep | PASS | completed / — | — |
| val-018 | validation / multistep | PASS | completed / — | — |
| val-019 | validation / recovery | PASS | refused / INSUFFICIENT_INFORMATION | — |
| val-020 | validation / recovery | PASS | completed / — | — |
| val-021 | validation / recovery | PASS | completed / — | — |
| val-022 | validation / boundary | PASS | completed / — | — |
| val-023 | validation / boundary | PASS | refused / UNSUPPORTED_REQUEST | — |
| val-024 | validation / boundary | PASS | refused / UNSAFE_REQUEST | — |

## 分组与限制

- split=dev：计划 48，记录 48，{'PASS': 47, 'PARTIAL': 1}。
- split=validation：计划 24，记录 24，{'PASS': 24}。
- group=boundary：计划 9，记录 9，{'PASS': 9}。
- group=multistep：计划 18，记录 18，{'PASS': 18}。
- group=recovery：计划 9，记录 9，{'PASS': 9}。
- group=target：计划 36，记录 36，{'PASS': 35, 'PARTIAL': 1}。
- focus_tool=None：计划 36，记录 36，{'PASS': 36}。
- focus_tool=calculator：计划 6，记录 6，{'PASS': 6}。
- focus_tool=changed_files：计划 6，记录 6，{'PASS': 5, 'PARTIAL': 1}。
- focus_tool=code_search：计划 6，记录 6，{'PASS': 6}。
- focus_tool=find_tests：计划 6，记录 6，{'PASS': 6}。
- focus_tool=git_diff：计划 6，记录 6，{'PASS': 6}。
- focus_tool=read_project_context：计划 6，记录 6，{'PASS': 6}。
- project=fixture：计划 39，记录 39，{'PASS': 38, 'PARTIAL': 1}。
- project=requests：计划 9，记录 9，{'PASS': 9}。
- project=urllib3：计划 24，记录 24，{'PASS': 24}。

- 工具过程评分不证明最终答案正确或端到端质量。
- 新题是同类 HTTP/Python 仓库迁移；非独立人工或 sealed holdout。
- N/A 代表缺少观察机会；不应转换成 100%。
- 离线 Gold 路径和脚本回放不代表模型自主选择能力。

原始事实见 calls.jsonl，冻结题目见 cases.jsonl，自动分见 scores.json，复核意见单独填写 reviews.json。
