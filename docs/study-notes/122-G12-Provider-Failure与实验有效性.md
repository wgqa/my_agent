# 122. G12 Provider Failure 与实验有效性

## 1. 这次 Formal 到底发生了什么

`g12-system-c-formal-20260826-173039` 的 16 个 case 都在第一次 Decision
返回 `status=failed`、`failure_code=ACTION_PROVIDER_ERROR`。当时 HTTP 请求本身
返回了 200，但 Agent 的 provider 调用并没有产生可以进入 Tool loop 或
Finalization Guard 的正常 Decision。原始 artifact 保留不变；它原先写成的
`VALID / MANUAL GOLD PENDING` 由 reviewer 更正为
`INVALID / PROVIDER-PLANE FAILURE`。

这不是 System C 的 FAIL，也不是 Guard 的负面能力结论。provider calls=16、
iterations=16、tool calls=0、Guard blocks=0 说明 tested intervention 根本没有
被触达，因此 System C effect 和 A/B conclusion 都是 `NOT MEASURED`。

## 2. HTTP 200 不等于 provider 成功

Harness 的 HTTP 层只确认 endpoint 返回了一个 JSON response。产品 Runtime 会把
`AuthenticationError`、`RateLimitError`、`APIConnectionError`、`APIStatusError`
和其他 provider response failure 收敛为稳定的 `ACTION_PROVIDER_ERROR`；这是一
个有效的产品失败语义，但不是一次成功的 provider-plane experiment。

因此 evaluator 必须同时看 outer HTTP outcome 和 response 内的 stable
`failure_code`。`ACTION_PROVIDER_ERROR` 与 `ACTION_TIMEOUT` 会使整个 Formal run
无效，而不是把它们当成普通 System C case failure 继续做 PASS/MIXED/FAIL 或
Manual Gold。

## 3. Product reliability 与 experiment validity

产品把 provider exception 脱敏并稳定映射，是 product reliability 的一部分。
实验是否有效则是 evaluator 的另一层判断：如果所有 case 都在 provider plane
失败，evaluator 只能记录已尝试 case、失败 code 和失败前成本，不能声称已经测到
Tool acquisition、Evidence Sufficiency 或 Guard behavior。

这条边界不会吞掉其他产品结果。`ACTION_PARSE_FAILED`、duplicate Tool、budget
stop、Guard 的 `INSUFFICIENT_EVIDENCE_TO_FINALIZE` refusal、错误答案和证据不足
仍是 valid Agent outcomes，应该进入有效 run 的产品/能力分析。

## 4. 为什么不能评价 Guard

Guard 在 `FinalAnswerAction` 后、Runtime 创建 `completed` 前工作。provider-plane
failure 发生在第一次正常 Decision 之前，所以没有 Tool call，也没有 Guard block。
即使 evaluator 能保存一条 failed case，也不能从它推断“Guard 没有改善”或
“System C FAIL”；这只是 intervention 未被执行。

Runner 在发现 provider-plane failure 后允许停止后续请求，并保存 partial
diagnostics：attempted case IDs、completed case count、stable failure code 以及
provider/tool/iteration cost before failure。invalid artifact 不生成 Manual Gold
结论或 A/B capability conclusion。

## 5. Invalid 与 Fail 的区别

`FAIL` 表示实验有效，且 System C 在冻结的 benchmark、provider、Prompt、Tool
和 budget 条件下没有达到 acceptance contract。`INVALID` 表示无法用这次 run
测量该能力，例如 provider-plane failure、HTTP/response schema failure、错误
project binding 或 provenance drift。

有效的 FAIL 不得为了挑更好的结果重跑。只有 INVALID run 在完成 provider-plane
诊断并获得 reviewer 授权后，才允许整体重跑；旧 artifact 必须永久保留，不能
覆盖或改写成有效结果。单独挑表现差的 case 重跑仍不可以。

## 6. 实验记录规则

本次重分类单独记录在 evaluator-owned
`evaluation/gate12/system_c_invalid_run_v1.json`，其中保存原 artifact 的 SHA、
reviewer corrected classification、16/16 failure observation、Guard 未触达和
`formal_ab_conclusion=NOT MEASURED`。它不修改原 run，也不创建一个伪造的新 run。

下一步只能是 provider diagnostic 与 reviewer-authorized full rerun；本修复本身
不运行 Formal，不改变 Prompt、Runtime、Guard、Tool、benchmark 或 Gold。
