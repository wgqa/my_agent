# 80-Gate3最终Holdout与Gate3封卷复盘

> G3-CLOSE-10-HOLDOUT-OFFLINE-SEAL：把唯一一次正式 Holdout 结果（formal_holdout_run_id=cb157fd3837f）离线封档。本任务 0 LLM / 0 retrieval / 0 embedding / 0 Judge / 0 Holdout rerun，只读已产生 artifact 与 ledger。
> 日期：2026-08-14
> 状态：G3-HOLDOUT-09C-R5 = Reviewer accepted / CLOSED；Gate 3 final Holdout = VALID；G3-CLOSE-10 = REVIEW PENDING；Gate 3 = FINAL CLOSE PENDING（未自行写成 CLOSED）。

---

## 0. 一句话

Gate 3 唯一一次正式 Holdout 跑完了，结果是 `completed`。这一步把结果原样封档，并把 Gate 3 推到"只差 Reviewer 最后签发"的位置。

## 1. 09C 全流程时间线

- **09C-FINAL-SEALED-RUN（第一次正式执行）**：在进入模型执行前，sealed manifest 校验 fail-closed → attempt `41c991a839cb` = `invalid_infrastructure`。0 性能观测。根因 = executor 读 private manifest 字面字段 `case_count`（该键不存在），冻结 manifest 真实字段是 `holdout_case_count=12`。frozen raw SHA 未变，不是数据被换。
- **09C-R1（metadata forensic）**：确认字段名错位、数值 12 一致、frozen SHA 未变。
- **09C-R2（manifest compatibility）**：executor 对齐 `holdout_case_count`（= Reviewer accepted / CLOSED）。
- **09C-R3（replacement authorization）**：实现 Reviewer-gated replacement 授权机制（gate），不授权执行。
- **09C-R3-R1（preflight target）**：replacement preflight 目标绑定。
- **09C-R4（real replacement preflight）**：真实 ledger 上 PASS（replacement_candidate=True，0 副作用）。
- **09C-R5（唯一一次 replacement sealed run）**：Reviewer 显式授权，replacement attempt `5f5f0c7bef9b` 正式执行 → `completed`，formal_holdout_run_id=`cb157fd3837f`。
- **G3-CLOSE-10（本任务）**：离线封档 + 校验。

## 2. 正式 Holdout 结果（聚合，安全封档值）

完整聚合存 `docs/experiments/gate3_holdout_final.json`（只含安全聚合，无 case_id/query/Gold/answer/evidence/Judge 原文/本地路径/Key）。

- formal_holdout_run_id：`cb157fd3837f`
- source_commit：`e97f576f4f4e49367f33f4cbb8eb35e9fdf22e8b`
- system freeze `2ec11a69b173` / dataset freeze `257fa0d0a6d6` / eval `79a6bc0814a3` / case_count `12`
- attempt：original `41c991a839cb`/invalid_infrastructure（永久保留）→ replacement `5f5f0c7bef9b`/completed（replacement_of=`41c991a839cb`）
- generation：completed 8 / failed 4（系统行为性失败，计入正式结果）
- retrieval：obligation 18/21 = 0.857、full coverage 8/10 = 0.8、Hit@5 1.0、Recall@5 0.9、MRR 0.775、nDCG@5 0.795
- answer：obligation 8/21 = 0.381、full 4/10 = 0.4、pass 4/10 = 0.4、citation valid 6/6 = 1.0、unsupported 0、invalid judge 0、no-answer 4、zero-obligation 2

## 3. 一次性纪律如何保证

- 第一次正式 attempt（invalid_infrastructure）**永久保留**；普通 one-shot 逻辑（ledger 存在任何合法 attempt 即拒绝第二次）从不放宽。
- replacement 必须 Reviewer 显式授权，并带 `replacement_of_attempt_id` provenance；只允许一次，无 chain。
- 本封档 0 LLM / 0 retrieval / 0 embedding / 0 Judge / 0 rerun；未调参、未重跑、未改代码 / Prompt / 模型 / 数据；`rerun_count_after_final=0`、`post_holdout_tuning=false`、`holdout_content_public=false`。

## 4. 面试怎么讲

讲清 Gate 3 封卷线：第一次 sealed Holdout 因 evaluator 对 private manifest 字段名存在错误假设而 fail-closed（frozen SHA 证明不是数据被换、无性能观测）→ 独立审计 forensic → 修复 executor → Reviewer 显式授权 replacement → 唯一一次 replacement 正式执行 `completed` → 离线封档。整个过程中原 invalid-infrastructure attempt 永久保留，普通 one-shot 逻辑从不放宽，replacement 是带显式 provenance 的第二条审计记录而非"删除重跑"。

## 5. 当前状态

- G3-HOLDOUT-09C-R5 = **Reviewer accepted / CLOSED**
- Gate 3 final Holdout = **VALID**（formal_holdout_run_id=cb157fd3837f）
- G3-CLOSE-10-HOLDOUT-OFFLINE-SEAL = **REVIEW PENDING**
- Gate 3 = **FINAL CLOSE PENDING**（待 Reviewer 审完本封档提交后正式签发 CLOSED / FROZEN）
