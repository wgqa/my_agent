# PRODUCT-REPAIR-23 — Set A DEV/DIAGNOSTIC Before/After

> 一个通用 intervention（Repository Evidence Activation）的固定 Set A 前后诊断。
> **Set A 自此为 DEV / DIAGNOSTIC**，不是 independent validation。
> 冻结不变量：repos / pinned commits / questions / corpus / provider / model /
> 5/4/2 / runner 全部不变；唯一 Product 差异 = REPAIR-23 candidate
> `0eacf79472bfbfec634a5b40e61e75937802cec3`（router PROJECT_CODE fallback）。

## 1. Intervention（Provider-free 已验证）

`core/engineering_requirements.py` 新增 bounded lexical fallback
`_repo_navigation_intent()`，挂在优先级链最后（PROJECT_SCOPE 之后、
NO_ADDITIONAL 之前）：

1. 显式源码引用（源码/源代码/source code/codebase/代码库）→ PROJECT_CODE_V1；
2. 调用关系词（谁调用/调用者/调用链/调用关系/who calls/call chain/caller/callee）→ PROJECT_CODE_V1；
3. 位置词（哪个文件/哪个模块/哪个函数/哪里实现/实现位置/where is/which file/…）
   **且** 代码对象词（函数/模块/方法/逻辑/实现/代码/function/module/…）同时出现 → PROJECT_CODE_V1。

frozen profile 形状不变（PROJECT_CODE_V1 = project_code ×1）；优先级
CHANGE_TEST→DOCS_CODE→THEORY_CODE→DIAGNOSIS→PROJECT_CODE→NO_ADDITIONAL 不变；
无任何 Set A case-specific 词（provider-free 测试断言）。

## 2. Before / After（同一冻结 Set A，10 questions）

| Task | Before f73f267 | After 0eacf79 | Δ |
| --- | --- | --- | --- |
| A1 | completed，3 tools，project_code×2，[E6][E7]，PASS | completed，3 tools，project_code×2，[E6][E7]，PASS | **无 regression**（答案与引用一致） |
| A2 | completed，**0 tools**，知识库非答案，FAIL | completed，**3 tools**，registry.py L16-76 实证回答注册/查找机制，Agent 侧校验部分诚实声明证据未覆盖，**PARTIAL** | repo 取证启动 ✅ |
| A3 | refused INSUFFICIENT_INFORMATION，0 tools，FAIL | refused，0 tools，FAIL | 不变（问句无任何 fallback 词；属遗留） |
| B | refused，3 tools（DOCS_CODE 缺 project_doc） | refused，3 tools，同因 | 不变（next-hop，未修） |
| C | refused，4 tools（CHANGE_TEST 缺 project_test） | refused，4 tools，同因 | 不变（next-hop，未修） |
| D | refused，**0 tools**（citation 拦截偶然拒答） | refused，**4 tools**（先实际搜索再拒答），证据未留存 → INSUFFICIENT_EVIDENCE_TO_FINALIZE | 拒答机制从"偶然"变"查证后" |
| E-T1 | refused，0 tools | **completed**，3 tools，function_calls.py L121-181，答案 `from_response` @151 **与源码逐行核对一致**，PASS | 修复 ✅ |
| E-T2 | refused INSUFFICIENT_INFORMATION，0 tools | **completed**，2 tools，location 已答、调用点诚实声明未覆盖，PARTIAL | 修复 ✅（over-refusal 消除） |
| E-T3 | completed，0 tools，答非所问 FAIL | completed，0 tools，同 | 不变（知识型问题，未被迫路由——同时证明**无过度路由**） |
| E-T4 | completed，0 tools，docs↔code 未做 FAIL | completed，0 tools，同 | 不变（router 词表"对照"缺口仍在，未修） |

## 3. 主要指标

| 指标 | Before | After |
| --- | --- | --- |
| Strict | PASS 1 / PARTIAL 1 / FAIL 8 | **PASS 2 / PARTIAL 3 / FAIL 5** |
| 0-repo-tool 问题数 | 7/10 | **3/10**（A3、E-T3、E-T4） |
| 取得 repo evidence 的问题数 | 3/10 | **6/10**（A1、A2、B、C、E-T1、E-T2；D 做了 4 次工具但未留存 evidence） |
| Over-refusal（0 工具 INSUFFICIENT_INFORMATION） | 2 | **1**（E-T2 修复；A3 遗留） |
| PROJECT_CODE activation（repo 导航问题） | 0/4 | **4/4**（A2、D、E-T1、E-T2 全部激活） |
| Decision LLM calls | 21 | 28（+7 全部来自新启动取证的 4 题） |
| 总墙钟 | ≈54.2s | ≈65.8s |

## 4. 结论

- 卡片核心问题——"原来那批明显 repo-specific、却 0 tool 的问题，现在是否开始
  实际调查仓库？"——**是**：A2/D/E-T1/E-T2 四题全部从 0 工具变为实际取证；
  E-T1 直接给出与源码核对一致的精确答案（from_response @ instructor/v2/core/
  function_calls.py:150-151）。
- A1 无 regression；E-T3/E-T4 纯知识型问题保持 0 工具（fallback 未过度路由）。
- **B/C next-hop issue still present: YES**（未在本次范围，未顺手修）。

## 5. Verdict

**PRODUCT-REPAIR-23 = VALID / PROMOTED**
Evidence Acquisition blocker = **PARTIALLY REPAIRED**
（repo-question activation 已修复；B/C next-hop 读取目标错误、A3/E-T4 措辞
未覆盖、E-T3 wrong-subject grounding 仍遗留）

Recommended next issue: B/C next-hop evidence-kind targeting（find_tests 之后
不读 test 文件、DOCS_CODE 不读 project doc）。

## 6. Run identity

- Candidate: `0eacf79472bfbfec634a5b40e61e75937802cec3`（provider-free: 修复测试
  23 passed + 全量 2640 passed / 7 skipped / 0 failed + FULL_APP_SMOKE_OK）
- Runs: `runs_repair23/*.json`（与 `runs/*.json` 同一冻结契约）
- Before runs: `runs/*.json`（f73f267）
