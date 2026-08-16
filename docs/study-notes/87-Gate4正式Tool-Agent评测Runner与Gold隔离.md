# 87. Gate 4 正式 Tool-Agent 评测 Runner 与 Gold 隔离

> G4-EVAL-06B-01：把"冻结 24 Case + 冻结 corpus + clean source commit + 真实 Tool
> Registry + Bounded Runtime + Decision Provider + 15 项冻结指标"接成可复现正式评测框架。
> 本任务只 Fake/Scripted Provider + real Tool wiring + real corpus preflight，0 real LLM。
> 配套：`evaluation/gate4/{runner_models,evaluator,runner}.py`、`scripts/run_gate4_tool_use_dev.py`。

---

## 0. 一句话

评测器本身也是一段要审的程序。Gate 4 的 Runner 负责把"尺子（冻结数据）+ 被测系统
（Tool-Agent）+ 记分板（15 项指标）"按纪律接起来，并保证**模型看不到 Gold**、**任何
一道门不通过就一票否决（0 model call）**。

---

## 1. 为什么"benchmark 冻结"后还要审 Runner

数据冻结只保证"题和答案不变"。但**跑题的机器**可能把结果弄脏：

- 忘了 Gold 隔离 → 模型看到 expected tool，等于开卷考试；
- 漏了一道 gate（tracked 脏、corpus 换过）→ 结果对不上身份，却还出报告；
- 指标口径算错（84 误命中 184）→ 分数虚高；
- 自动 retry / 覆盖旧结果 → 数字不可复现。

所以 Runner 要和数据一样受审计：**"评测状态机"也要有测试**。本卡的核心产物就是
一个 0-LLM harness——用 Scripted Provider 驱动真实 Tool，把整个状态机跑一遍，
证明它不会漏 Gold、不会算错指标、不会跳过 gate。

---

## 2. Gold leakage 是什么

Gold = 期望答案（category、expected tool、required_tools、assertions、rationale…）。

如果模型在决策时能看到这些，评测就退化成"复述答案"。**两阶段 Gold 隔离**：
- **Phase A 执行**：模型只见 `query + ToolSpecs + previous observations`，其他一律
  不给；执行完先落盘 `execution_results.jsonl`；
- **Phase B 评测**：重新加载冻结 Gold，把 execution + Gold **离线**评分。

两层之间用 case_id 集合硬校验：execution 的 case_id 集合必须精确等于 Gold 的 24 个，
多一个、少一个、重复一个全部 fail。execution artifact 还做**结构化防泄漏**：只允许
case_id / status / answer / reason / failure / counters / trace / 安全 decision 摘要
等字段，测试逐字段校验不含任何 Gold-only 字段。

> **安全 decision 摘要**：`RecordingDecisionProvider` 只记 iteration / action_type /
> tool_name / failure_code / call_metadata（provider/model/prompt 版本/SHA/toolset
> SHA/tokens/latency），**不记录 raw output、CoT、reasoning_content、API key**。这样
> 正式实验可以统计"调了几次模型、花了多少 token、用了哪个 prompt"，但拿不到敏感原文。

---

## 3. execution 与 evaluation 为什么分离

**执行**是运行时行为（模型 + Tool 真实跑）；**评测**是离线裁判（Gold + assertion）。

- 分离后，生成与判分用**不同时间、不同代码路径**，天然防止"边跑边改答案"；
- 执行先落盘，后续评测可离线重放（provenance repair 也能做，见 Gate 3 07A）；
- 判分可独立测试：一个 Scripted Provider 造出已知轨迹，评测器必须算出已知分数。

---

## 4. source commit / corpus / Toolset / Prompt 四层身份

`run_id = SHA256(canonical config)[:12]`，身份绑四层：

1. **source_commit**：git HEAD，且前置要求 tracked clean（不允许 CLI 手填假装身份）；
2. **corpus**：`corpus_id`（ExperimentCorpus 按 relative path + raw SHA + size 算）+ file_count；
3. **toolset_sha256**：模型实际看见的 Tool 集合的哈希（`compute_toolset_sha256(registry)`）；
4. **prompt**：`prompt_version` + `prompt_sha256`（决策模板身份）。

外加 `evaluation_set_id` / `dataset_jsonl_sha256` / `code_reference_commit` 把数据也
锁进身份。任一变化 → run_id 变 → 结果不能互相冒充。**API key、时间、本地路径、
output root 不进入身份**——它们不该影响"这道题跑的是哪个版本"。

## 5. code Gold 也要防"被后续工程改坏"

benchmark 的 code_search Gold 绑定 `91627bb` 的符号路径。正式 Runner 的 source
commit 比它新，所以加一道硬门：

```bash
git diff --name-only 91627bb...HEAD -- core/tool_agent core/agent_runtime
# 必须为空
```

核心代码面一旦变过，旧 benchmark 的 code Gold 可能失效——这时**不能偷偷继续用旧
benchmark**，而要让 Reviewer 决定是否生成新数据版本。

---

## 6. 为什么模型失败不自动 retry

Runtime 一次 Decision 返回 `ACTION_TIMEOUT / ACTION_PROVIDER_ERROR / ACTION_PARSE_FAILED`，
这是该 case 的**正式系统行为**：记录、进入下一个 case，**不重调同一 case**。理由：

- 自动 retry 会把"模型真的不稳"掩盖成"偶发一次"；
- retry 会打破调用上限（24×5=120）与成本预算；
- 真实评测想要的是"Agent 在约束下的真实表现"，不是"被救过几次的表现"。

未知程序异常 / 基础设施错误 → **abort 整场 run，保留现场（partial）**，不
restart / resume / overwrite，交给 Reviewer 判定。

## 7. 为什么 public Dev 也不能随便刷结果

即便 Dev 数据公开，**run 身份与 gate 纪律仍不可绕过**：

- 每个 run 绑定 tracked-clean 的 source commit，脏工作区跑不出数字；
- 输出目录已存在 → `FileExistsError`，不覆盖（先写 `<run_id>.partial`，成功才原子
  rename 成 `<run_id>`）；
- `--execute` 必须 `GATE4_TOOL_USE_EXECUTION_AUTHORIZED=1`，缺了 0 model call。

这样"刷一个更好看的数字"需要真的改代码/改题，而不是靠重跑或覆盖。

## 8. numerator / denominator / zero-denominator

每项指标保存 `{numerator, denominator, value}`，**不掩盖无分母**：

- 全场 0 次 ToolCall 时，`tool_error_rate` 与 `unnecessary_tool_call_rate` 的
  `value = null`（而不是伪造 `0.0`）；
- `first_tool_accuracy` 分母只含 `expected_first_action == tool_call` 的 case；
- `allowed_sequence_match_rate` 分母固定 = 4（只算 multi-step）。

## 9. micro coverage vs case accuracy

- **case accuracy**（first_action / termination…）：每 case 一个 0/1，然后求比例；
- **required_tool_coverage** 是 **micro obligation**：每个 case 的每个 required tool
  算 1 个 obligation，同一个工具被调 3 次仍只覆盖 1 个 obligation。分母 = 全部
  required-tool obligation 总数。这样才能量化"该用的工具到底用了几个"，而不是
  把"24 道题里几道全对"当唯一信号。

## 10. deterministic assertion 的局限

`answer_number_equals` 用**数字 token 提取 + Decimal 数值比较**（不是
`str(expected) in answer`，否则 84 会误命中 184）。`path_contains` 先 `\→/` 归一。
但这些都只测"答案文本里有没有/对不对"，**不等于语义正确**——模型可能给出正确数字却
推理错误，或答非所问却命中子串。protocol 已明确 final_answer_correct_rate 是
**deterministic assertion proxy**，不夸大。语义级评测才需要人工标注或独立 Judge。

## 11. safe Provider metadata

正式实验想统计成本/延迟/版本，但 Provider 里全是敏感内容。所以用一个 evaluation 层
wrapper `RecordingDecisionProvider`：delegate 原 provider 的 `decide()`，只额外记录
安全事实（call metadata 里的 tokens/latency/prompt 版本/toolset 哈希）。**不获得 raw
response / CoT / key**，Runtime 仍只依赖原来的 Provider Protocol，零侵入。

## 12. artifact manifest

每个正式 run 产出 7 个 artifact（run_config / execution_results / case_scores /
metrics / result / report / artifact_manifest）。`artifact_manifest.json` 记录每个文件
的 `sha256 + size_bytes`（**不含本地绝对路径**），任何人拿到都能复核这些文件没被
改过。run_config 把身份（run_id 依赖的一切）固化下来，跨机器可复现。

## 13. preflight 与 formal execution

- **preflight**（`--preflight-only`）：全部 gate + 建真实 BM25 索引 + 构造三个真实
  Tool + 验证 provenance，**0 model call**，输出 PASS/FAIL 报告；
- **formal execution**（`--execute` + 授权 env）：preflight 通过后才有资格真正调
  模型；本任务不设授权变量，所以 `--execute` 也只会得到"0 model call + 拒绝"。

## 14. Fake LLM + Real Tool 如何验证评测状态机

用 **Scripted Provider**（返回脚本化 AgentDecisionOutcome）驱动**真实 Tool**
（Calculator/CodeSearch/KnowledgeSearch handler），跑完整 24 case：

- 构造一个"完美 Agent"（每个 case 都按 Gold 的 required tools 走正确序列、给出满足
  assertion 的答案）→ 断言所有适用 accuracy = 1；
- 构造"坏 Agent"（用错工具、超预算、parse 崩、refuse 错原因）→ 断言对应指标被如实
  记下来；
- 验证 execution artifact 无 Gold、provider 无 key/CoT、case_id 集合相等、
  total decision calls ≤ 120。

这样即使一个真实模型都不调，也能证明"评测器本身是可信的"。

## 15. 面试问答

**Q1：为什么评测器本身需要测试？**
因为评测器是决定分数的人，它漏 Gold、算错口径、跳过 gate 都会让分数失真。用
Fake LLM + Real Tool 把整个状态机跑通，是在"造尺子的尺子"上建立可信度。

**Q2：两阶段 Gold 隔离具体怎么防泄漏？**
执行阶段模型只见 query + ToolSpec + observations；execution artifact 只允许安全字段
（case_id/status/answer/counters/trace/decision 摘要），结构化校验不含任何
Gold-only 字段；评测阶段才离线加载 Gold，并用 case_id 集合精确相等做硬校验。

**Q3：为什么自动 retry 是评测的大忌？**
retry 掩盖模型真实不稳、打破调用上限与成本预算。真实评测要的是"约束下的真实表现"。

**Q4：run_id 为什么绑四层身份？**
source commit / corpus / toolset / prompt 任一变化都改变被测系统或输入，run_id 必须
跟着变，否则不同版本的结果会互相冒充。

**Q5：denominator=0 时为什么要 null 而不是 0.0？**
0.0 暗示"确实测过且结果是 0"，掩盖了"根本没有分母"的事实。null + 保留
numerator/denominator 才不会撒谎。

---

## 16. 代码阅读路线

1. `evaluation/gate4/runner_models.py`：`Gate4ExecutionCase`（只 case_id+query）、
   `DecisionSummary`（安全摘要）、`Gate4ToolUseRunConfig`（canonical identity →
   run_id）、`RecordingDecisionProvider`（safe wrapper）；
2. `evaluation/gate4/evaluator.py`：6 种 assertion 精确语义 → `evaluate_case` →
   `compute_metrics`（15 项，numerator/denominator/value）；
3. `evaluation/gate4/runner.py`：preflight gates（tracked clean / dataset identity /
   corpus provenance / code-gold diff / no-overwrite / auth）→ Phase A 执行 →
   Phase B 评测 → artifact + 原子 finalize；
4. `scripts/run_gate4_tool_use_dev.py`：CLI（--preflight-only / --execute）；
5. `tests/test_gate4_tool_use_runner.py`：0-LLM harness（perfect run / gate 拒绝 /
   Gold 隔离 / 指标语义）。

## 17. 边界与后续

- 本任务 0 real LLM / 0 formal run / 0 Prompt 调优 / 0 Tool/Runtime 改动；
- 正式 G4-EVAL-06B execution = **BLOCKED** pending Reviewer 接受 harness；
- 下一任务：Reviewer 审计 06B-01 后决定是否放行唯一一次正式执行（届时设置
  `GATE4_TOOL_USE_EXECUTION_AUTHORIZED=1`，用冻结的 deepseek/deepseek-chat 配置）。
