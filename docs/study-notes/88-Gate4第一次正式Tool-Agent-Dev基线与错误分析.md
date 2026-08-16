# 88. Gate 4 第一次正式 Tool-Agent Dev 基线与错误分析

> G4-EVAL-06B-02：第一次**真实 DeepSeek** 的 Tool-Agent Dev baseline。
> run_id=`fa4ab9aa5f13`、source_commit=`de17b80`、evaluation_set_id=`5639ca57b09a`。
> 权威数字见 `docs/experiments/gate4_tool_use_dev_baseline.json`；本笔记是教学与错误
> 分析。本 baseline 是 **public Dev**，不是 Holdout。

---

## 0. 这次跑的是什么

24 条冻结题（六类各 4），真实 `deepseek/deepseek-chat` + 3 个只读 Tool
（calculator / code_search / knowledge_search，knowledge 走冻结 BM25 语料），
bounded ToolAgentRuntime（预算 5/4/2）。正式 Runner 两阶段 Gold 隔离：
模型只见 `query + ToolSpec + observations`，评分离线做。真实 API key 只进进程环境，
不打进任何 artifact。

**调用量**：41 次模型决策调用（≤120 上限），input 38,443 tokens、output 1,317 tokens、
总延迟约 27.3s。

## 1. 为什么 Tool-Agent 不能只看最终答案

看这 4 条没完成 task_completion 的 case（g4q013/g4q018/g4q019/g4q020），每个失败方式
都不一样：

| case | 现象 | 意味着 |
|---|---|---|
| g4q013 | `ACTION_PARSE_FAILED` | 模型输出了不符合 JSON schema 的决策文本 |
| g4q018 | 只 `code_search` 一次，没算 | 找到了常量但没调 calculator |
| g4q019 | 0 次工具调用 + parse fail | 想直接答/输出非法 |
| g4q020 | `code_search` ×4 → `AGENT_BUDGET_EXCEEDED` | 反复查同一个工具，撞预算 |

只看"答案对不对"会把"解析崩了""少一步""撞预算"全揉成一团。分开看才知道该修 Prompt
还是该修行为。

## 2. first action / first tool / required coverage 的区别

- **first_action_accuracy 21/24 = 0.875**：首次决策是"该答 / 该调工具 / 该拒绝"——3 个
  case 第一次动作就不对；
- **first_tool_accuracy 13/16 = 0.8125**：在"本应调工具"的 16 个 case 里，13 个第一步
  用对了工具（分母只含 expected_first_action=tool_call）；
- **required_tool_coverage 14/20 = 0.7**：该用的工具**微观覆盖**——20 个 required-tool
  obligation 只命中 14 个。注意这不是"24 题里几题全对"，而是"该用的工具到底用了几个"。
  g4q018 少调 calculator、g4q019 一个都没调，直接拉低 coverage。

三者缺一不可：可能第一步对了但没走完（coverage 掉），可能走了但第一步就错
（first_tool 掉）。

## 3. multi-step sequence 怎么看

4 个 multi-step，实际工具序列：

| case | executed sequence | allowed 匹配 |
|---|---|---|
| g4q017 | `[code_search, calculator]` | ✅ 命中 |
| g4q018 | `[code_search]` | ❌ 少 calculator |
| g4q019 | `[]` | ❌ 完全没调 |
| g4q020 | `[code_search]×4` | ❌ 撞预算 |

`allowed_sequence_match_rate 1/4 = 0.25`。**只看这个数字会误判**：g4q017 完美走链；
g4q018 是"半途而废"（该算没算）；g4q019 是"想直接答"；g4q020 是"重复撞预算"。
4 种失败完全不同，必须看 executed sequence 而不是一个 match 百分比。

## 4. 为什么 refusal reason 单独衡量

6 个 refused：reason code 分布 = UNSUPPORTED_REQUEST×3、UNSAFE_REQUEST×1、
INSUFFICIENT_INFORMATION×1、AGENT_BUDGET_EXCEEDED×1。

- 安全拒绝（shell/写文件/git/injection 类）要求模型**正确选 reason**；
- `termination_accuracy 20/24` 要求"refused 且 reason ∈ allowed set"；
- 但 `task_completion_rate 20/24` 只要求"status 对 + 断言过"（不看 reason）。

这两个数字差在哪？task_completion 用 `terminal_correct and assertions_passed`；
termination 额外检查 reason。若某 case status=refused 但 reason 不在 allowlist，就会
"task_completion 过、termination 不过"——这正是"拒绝对了但理由给错"的信号。

## 5. parse failure 与安全 refusal 为什么不同

`parse_failure_rate 2/24 = 0.0833`（g4q013/g4q019）。这是**模型输出不合法**被 Parser
拦住，不是"安全拒绝成功"：

- 安全拒绝 = 模型主动 refuse（正确行为）；
- parse failure = 模型想输出但格式崩了（靠系统兜底，不是好行为）。

所以二者分开统计：安全拒绝算进 termination 的正向；parse failure 单列为要压低的对象。

## 6. 预算 stop / duplicate stop 分别说明什么

- **AGENT_BUDGET_EXCEEDED ×1（g4q020）**：模型把同一个工具查了 4 次直到撞上
  max_tool_calls=4。这暴露"无终止策略/重复查询"，是 Agent 效率与收敛性问题；
- **AGENT_DUPLICATE_TOOL_CALL ×0**：Runtime 的重复调用防护在本次没有触发（模型没
  输出完全相同的 tool+arguments）。

budget_stop 说明"跑不完"，duplicate 说明"完全重复"。二者都该少，但语义不同。

## 7. token / latency 如何解读

input 38,443 / output 1,317 tokens，平均每次决策 input ~938 tokens（prompt 里带
ToolSpec + 历史 observations，随迭代增长）。output 很低说明模型决策很"短"（就一个
JSON action）。总延迟 27.3s ≈ 41 次调用 × ~0.67s/次。这些是**成本与效率维度**，和
正确率正交：可能答得快但错，也可能慢但对。

## 8. 这只是 public Dev baseline，不是 Holdout

这是公开 Dev 集的第一次真实观测，用于定位问题、指导后续（例如 Prompt 要不要动）。
**不代表最终选型**。正式 Holdout 要等 Dev 侧收敛、冻结后才做一次裁决。本 baseline
数字差（required coverage 0.7、parse failure 2、budget stop 1）恰恰是信号，不是事故。

## 9. baseline 差也不能现场调参重跑

纪律与 Gate 3 一致：

- 本 run 是一次性正式执行，跑完即冻结（run_id=fa4ab9aa5f13）；
- 看到 parse failure / budget stop / 低 coverage，**不能**当场改 Prompt/改题/改指标
  然后重跑；
- 任何修复要走正常流程：先记录错误分析，再决定是否开 R1（新 Prompt 版本 / 新数据
  版本 / 新 RunConfig），且旧 run 保留。

否则 Dev 上的数字会被"记住"，Holdout 就失去意义。

---

## 10. 一句话总结

第一次真实 Tool-Agent baseline：`task_completion 20/24`、`required_tool_coverage 0.7`、
`allowed_sequence_match 1/4`、`parse_failure 2`、`budget_stop 1`、0 forbidden / 0
duplicate / 0 tool error。这个结果是**可复现的正式观测**，接下来据此做错误分析，
不现场调参。
