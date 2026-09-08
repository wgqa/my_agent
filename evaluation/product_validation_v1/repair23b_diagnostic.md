# PRODUCT-REPAIR-23B — Requirement-Guided Next-Hop Acquisition: VALID NEGATIVE EXPERIMENT

> 一个 prompt-only intervention（grounded_v2 next-hop guidance）的固定 Set A
> 前后诊断。**Set A = DEV / DIAGNOSTIC**。结论：**ROLLBACK**；23 系列到此结束，
> 无 23C。

## 1. Mechanism（candidate `8e1732c`，已回滚）

`decision_prompt.py` 新增后继 profile
`engineering_agent_decision_prompt_unified_kind_aware_grounded_v2`
（= frozen grounded_v1 模板 + "Missing-Evidence Next-Hop Acquisition policy"
后缀；v1 SHA `c465defe…` 保持不变），`api/app.py` 切换 Product 组装到 v2。
后缀规则：missing_evidence_groups 含某 kind 时下一跳必须为该 kind 产出
evidence（project_test：find_tests 候选 → read_project_context 测试路径；
project_doc：code_search(artifact_kind=project_doc) → read；evidence 已满足
→ 不再加 Tool）。零控制面改动：无新 loop/tool/预算/二次 LLM；control state
未变。

## 2. 冻结 Set A 前后（before = runs_repair23 @0eacf79；after = runs_repair23b @8e1732c）

| Task | Before（23A） | After（23B） | Δ |
| --- | --- | --- | --- |
| B（主要目标） | refused，3 tools，读了代码、**无 project_doc** | refused，4 tools（code_search→read→code_search→read），**仍无 project_doc** | **无改善：模型未跟随 doc next-hop 指引** |
| C（主要目标） | refused，4 tools，change+code，未读任何 test 文件 | refused，4 tools，change+**project_test×1**（missing kind 的下一跳按指引真实执行） | **目标机制达成**，但 final answer 随后被 citation/binding 拦截（超范围已知限制），terminal 不变 |
| A1 | completed / 3 tools / PASS | completed / 2 tools / 答案仍含 config.py+agent.py+有效引用 | **无 regression** |
| E-T2 | completed，2 tools，PARTIAL | **refused INSUFFICIENT_INFORMATION，0 tools，FAIL** | **regression** |
| E-T4 | completed（诚实"未找到代码"），FAIL | **refused INSUFFICIENT_EVIDENCE_TO_FINALIZE** | terminal regression（同为 FAIL 级） |
| A2 / A3 / D / E-T1 / E-T3 | — | 与 23A 等价（A2 PARTIAL、A3 FAIL、D PARTIAL、E-T1 PASS、E-T3 FAIL） | 不变 |
| 总分布 | PASS 2 / PARTIAL 3 / FAIL 5 | PASS 2 / PARTIAL 2 / FAIL 6 | **变差** |

## 3. 判定

按任务卡标准："B/C 至少明显改善其中一个且无明显 regression → PROMOTE；
基本没改善或成本/退化明显 → ROLLBACK"：

- C 的目标机制（missing kind 下一跳）单点验证成功，但用户可见 terminal 无改善
  （随后被 citation 合规拦截——23 系列明确不修）；
- B 的 doc next-hop 完全未被模型跟随；
- E-T2、E-T4 两个 completed→refused 的明显 regression；
- 总分布变差。

→ **ROLLBACK**（`git revert 8e1732c` → `36739aa`；core/api/tests 与 cf663d4
逐字节一致；rollback 后全量 2640 passed / 7 skipped / 0 failed +
FULL_APP_SMOKE_OK）。

**PRODUCT-REPAIR-23B = VALID NEGATIVE EXPERIMENT / ROLLED BACK。**
教训（记录，不再堆规则）：对缺失 kind 的 prompt 指引能在部分场景改变下一跳，
但 (a) 指引遵循度因问题而异（B 忽略），(b) 只要 citation 合规拦截还在，取证
改善无法转化为 terminal 改善，(c) 更长的 system prompt 对未阻塞问题存在行为
扰动风险。

## 4. 23 系列收尾

- PRODUCT-REPAIR-23（23A，router fallback）= VALID / PROMOTED（Evidence
  Acquisition blocker = PARTIALLY REPAIRED）。
- PRODUCT-REPAIR-23B（prompt next-hop guidance）= VALID NEGATIVE EXPERIMENT /
  ROLLED BACK。
- **23 到此结束，无 23C。**
- grounded_v2 仅作为历史实验身份存在于 git 历史（`8e1732c` / `36739aa`），
  当前 Product prompt 仍为
  `engineering_agent_decision_prompt_unified_kind_aware_grounded_v1`
  （SHA `c465defe7f9504d7cfb137748ba96fb90cf7bf049c7ca7a93d3f7f56945ebcdf`）。

## 5. Residual Product limitations（记录，不顺手修）

1. B/C next-hop acquisition 仍未解决（23B 的负结果本身是证据：prompt-only
   指引不充分）。
2. citation 合规与被拦截答案可观测性（B/C/D/E 多次 INSUFFICIENT_EVIDENCE_
   TO_FINALIZE 的直接下游；被拦截答案文本与 binding 细节不可观测）。
3. A3 措辞（"涉及的文件与关键函数"）不被 router fallback 覆盖。
4. E-T4 wording："对照"不在 frozen consistency 词表。
5. E-T3 wrong-subject semantic grounding（知识语料内容冒充 repo 回答）。
6. 多轮 context-resolution 方差（E-T2 在两次诊断间的行为差异归因存在不确定性）。

## 6. NEXT

**NEXT = PRODUCT-ENGINEERING-24 / NOT STARTED**（19→27 冻结路线下一站；
不得自行开始）。
