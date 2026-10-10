# offline_facade_smoke_20261009_c

当前产品装配脚本回放（无模型）

代码 HEAD：`bdd9faf6addc1ec633de3165a757cb3c2ca866f3`；实际业务 SHA：`6a679bd9475e3f2f9ecfb8c9ef2b818ae641382de042e2fe0c1850de51e6037c`。
计划 9 题，已记录 9 题，有效 9 题，无效 0 题，未运行 0 题。

原始状态与自动判分分别保存。复核队列尚未人工裁决；不能把自动 PASS 称作独立人工验收。

| 指标 | 结果 / 分母 |
|---|---|
| 必需材料获取 | 100.0% (14/14) |
| 整题材料齐全 | 100.0% (8/8) |
| 不可替代工具义务 | 100.0% (4/4) |
| 合理首步 | 100.0% (5/5) |
| 已解析执行调用的目标正确 | 100.0% (16/16) |
| 首次动作解析有效 | N/A (0 个观察机会) |
| 修复后动作解析有效 | N/A (0 个观察机会) |
| 解析修复成功 | N/A (0 个观察机会) |
| 多材料过程 | 100.0% (2/2) |
| 已触发故障的恢复 | 100.0% (1/1) |
| 停止行为 | 100.0% (9/9) |

Provider 调用已知数量：0；缺 metadata 的逻辑调用：34。
已知 input/output token：None / None；缺 usage 的实际调用数：0 / 0。
工具执行：16 次；不当尝试 0 次，护栏拦截涉及 0 题。

## 逐题自动结果

| 题号 | 集合 / 任务组 | 判分 | 原始停止状态 | 缺口 |
|---|---|---|---|---|
| dev-001 | dev / target | PASS | completed / — | — |
| dev-009 | dev / target | PASS | completed / — | — |
| dev-025 | dev / multistep | PASS | completed / — | — |
| dev-029 | dev / multistep | PASS | completed / — | — |
| dev-039 | dev / recovery | PASS | completed / — | — |
| dev-040 | dev / recovery | PASS | completed / — | — |
| dev-041 | dev / recovery | PASS | completed / — | — |
| dev-046 | dev / boundary | PASS | refused / UNSAFE_REQUEST | — |
| dev-048 | dev / boundary | PASS | completed / — | — |

## 分组与限制

- split=dev：计划 9，记录 9，{'PASS': 9}。
- group=boundary：计划 2，记录 2，{'PASS': 2}。
- group=multistep：计划 2，记录 2，{'PASS': 2}。
- group=recovery：计划 3，记录 3，{'PASS': 3}。
- group=target：计划 2，记录 2，{'PASS': 2}。
- focus_tool=None：计划 7，记录 7，{'PASS': 7}。
- focus_tool=calculator：计划 1，记录 1，{'PASS': 1}。
- focus_tool=read_project_context：计划 1，记录 1，{'PASS': 1}。
- project=fixture：计划 9，记录 9，{'PASS': 9}。

- 工具过程评分不证明最终答案正确或端到端质量。
- 新题是同类 HTTP/Python 仓库迁移；非独立人工或 sealed holdout。
- N/A 代表缺少观察机会；不应转换成 100%。
- 离线 Gold 路径和脚本回放不代表模型自主选择能力。

原始事实见 calls.jsonl，冻结题目见 cases.jsonl，自动分见 scores.json，复核意见单独填写 reviews.json。
