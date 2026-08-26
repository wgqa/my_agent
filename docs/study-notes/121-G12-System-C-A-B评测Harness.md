# G12 System C A/B 评测 Harness

## 这份 Harness 做什么

G12-04D 的产物是 System C 的 evaluator harness，不是新的产品能力。它把同一套 frozen 16-case benchmark 发给两个已经由操作者启动的 API：

- API A 绑定 frozen `my_agent` checkout；
- API B 绑定 frozen `pydantic-ai` checkout；
- 两个 API 使用同一份 System C product、Prompt、Tool registry、Knowledge 和 provider 配置。

请求体只包含 `question`。`case_id`、task family、evidence requirement、Gold obligation 和 source proof 都留在 evaluator 一侧。

## Product requirement 与 evaluator Gold

Product-side requirement router 是通用的 bounded logic。Evaluator 不能读取 router 的结果来替代 benchmark contract，也不能提前用 16 个 frozen question 调 router recall。

Frozen case 的 Gold requirement 是 evaluator-side structural metric：

- Theory <-> Code 要有 `knowledge`，并有 `project_code` 或 `project_doc`；
- Change Impact <-> Test 要有 `project_change` 和 `project_test`；
- Diagnosis 要有 `project_code`，cross-file case 还要有足够多的 distinct code paths；
- Docs <-> Code 要同时有 `project_doc` 和 `project_code`。

因此 Router 漏判时，evaluator 仍然可以独立判断最终 public evidence 是否满足 frozen case 的 shape。`completed` 加上 evaluator-side insufficiency 仍计为 `premature_finalization`，不能被 product route 的缺失掩盖。

## Guard 指标

System C safe trace 允许 Guard 的公开诊断字段：`guard_status`、`missing_evidence_groups`、`distinct_project_code_paths` 和 `required_min_distinct_project_code_paths`。它们只描述系统发生了什么，不保存模型问题、答案、Prompt 或推理。

Harness 自动统计：

- `guard_block_count`：一个 case 中 `finalization_guard_blocked` event 的数量；
- `guard_blocked_cases`：至少发生一次 block 的 case 数；
- `guard_recovery_attempted_cases`：block 后出现后续 Tool activity 的 case 数；
- `guard_recovery_succeeded_cases`：同时满足 block、之后的 structural evidence progress、最终 `completed`、最终 evaluator evidence sufficient 的 case 数；
- `guard_final_refusal_cases`：最终因 Guard 终止而拒绝的 case 数；
- `guard_specific_refusal_count`：`status=refused` 且 `reason_code=INSUFFICIENT_EVIDENCE_TO_FINALIZE` 的 case 数。

`block + completed` 不是 recovery success。若最终 evidence 仍不足，仍是 premature finalization，不能因为模型最后输出了答案就算恢复成功。

## Automatic 与 Manual Gold

Automatic evaluator 只测 evidence kind、数量、distinct path、Tool usage、Guard trace、预算和成本等确定性结构。它不判断答案语义、Gold obligation 是否被正确解释、evidence 是否真的支持 claim，也不判断 Docs label 是否正确。

每个 run 都先生成 `manual_review_template.jsonl`。其中保留 Gold obligations/proofs、Agent answer 和 public evidence references，但 reviewer 字段初始化为 `NOT SCORED`。因此 real run 结束后状态是：

`VALID / MANUAL GOLD PENDING`

在 Manual Task Success 与 Claim Grounding 填入前，acceptance snapshot 只能是 `PENDING_MANUAL_REVIEW`，不能提前宣布 PASS、MIXED 或 FAIL。完成 Manual Gold 后，离线 classifier 才按照 04A contract 检查完整 PASS/MIXED/FAIL gates；不需要重新请求 provider。

## Cost 与 provenance

`provider_call_count` 是每个 `decision_completed` event 的本地累计值，case-level 统计必须把每个 decision event 相加。例如 `[1, 1, 1, 1]` 是 4，`[1, 2, 1]` 也是 4，不能取最大值。

Manifest 同时记录：

- Baseline product commit `0a1f42e...`；
- System C product commit `65ee45e...`；
- Baseline 到 System C 的 exact 04C product intervention paths；
- System C commit 到 evaluator HEAD 的 product diff 为零；
- dataset、acceptance contract、Prompt、Repair、budget、registry 和 Knowledge identity。

这区分了 A/B 的 product factor 与 04D evaluator 文件。HTTP 连接失败、错误 endpoint、错误 project binding、dataset drift 或 control drift 是 `INVALID`；Guard refusal、evidence insufficiency、duplicate、parse failure、budget stop 和错误答案则是有效的 System C outcome，不能被当作 infrastructure failure。

## 一次正式运行

Harness 由 reviewer 接受后，System C Formal 原则上只运行一次完整的 16 cases。有效的 PASS、MIXED 或 FAIL 不能为了挑选更好的结果而重跑，也不能只重跑单个 case。只有 infrastructure invalid 才能在修复后整体重跑；旧 invalid artifact 必须保留。

本任务只完成 harness 和 deterministic tests。System C real-provider Formal 尚未运行。
