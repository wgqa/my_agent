# PRODUCT-VALIDATION-22 — Fresh User Scenario Baseline (Set A) Summary

> 首次用真实 Provider（DeepSeek）+ 陌生 AI/仓库 + 真实用户任务验证 Release 2.0
> Product（commit `f73f267`，grounded prompt
> `engineering_agent_decision_prompt_unified_kind_aware_grounded_v1`）。
> 场景契约冻结于正式运行前（freeze commit `57bbe1b`）；全部 7 个任务 / 10 个
> 问题一次连续跑完，未做任何中途修改；本任务对 Production 零修改。

## 0. Identity（Observed fact）

| 项 | 值 |
| --- | --- |
| Product commit | `f73f267ccf2300199e0c5183490fa63aeb962ae3` |
| Prompt | `engineering_agent_decision_prompt_unified_kind_aware_grounded_v1` / `c465defe…ebcdf` |
| Provider / Model | deepseek / deepseek-chat（planner 同源；DECISION_TEMPERATURE=0） |
| Knowledge corpus | `wgqa/agent_data@179f18e8`，corpus_id `870e5864df67`，37 files / 215 chunks / bm25（运行时 verified=True） |
| Tool budget | 5 / 4 / 2（冻结） |
| Fresh repos | vanna `@365d0617`、instructor `@5ea35cdb`、instructor_change `@2b64e497` + 未提交应用的 security-fix diff（13 modified + 1 untracked test） |
| Scenarios | 7 tasks：A×3、B×1、C×1、D×1、E multi-turn×1（4 turns）＝10 questions |
| Freeze / runs | freeze commit `57bbe1b` 先于第一条正式运行；runner crash 修复（import bootstrap，评估工具层，发生在任何请求之前）披露于 §7 |
| Contamination | Set A：一旦被用于指导 PRODUCT-REPAIR-23 的 Product 修改，立即退化为 Dev/Diagnostic Set；PRODUCT-ACCEPT-25 必须换 Fresh Set B |

## 1. Result table（每题一句结论）

| Task | Repo | Terminal | Tools | Decision LLM calls | Latency | Strict | 一句话结论 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A1 | vanna | completed | 3 | 4 | 6.6s | **PASS** | temperature 链路（config.py:120 → agent.py:1235 → middleware → provider payload）全部答对并引用 [E6][E7]，是整套唯一完整成功案例 |
| A2 | vanna | completed | 0 | 1 | 3.7s | FAIL | 0 次工具调用，只用知识库泛谈 Function Calling，答案明说"无法确认 vanna 实现"——以 completed 状态交付非答案 |
| A3 | instructor | refused | 0 | 1 | 2.5s | FAIL | 对完全可答的问题 0 工具直接 INSUFFICIENT_INFORMATION 拒答（over-refusal） |
| B | vanna | refused | 3 | 4 | 7.3s | FAIL | 检索链路正确（找到并读了 generate_sql 所在 base.py），但按路由要求还需读 project_doc；第 3 次工具浪费在重复 code_search，最终 finalization 拦截 |
| C | instructor_change | refused | 4 | 5 | 9.4s | FAIL | changed_files→git_diff→find_tests→读代码链路启动正确，但从未读任何测试文件，project_test 义务始终未满足，预算耗尽硬停止 |
| D | vanna | refused | 0 | 1 | 2.9s | PARTIAL | ground truth 确认 HyDE 模块不存在；用户拿到拒答（结果正确），但这是 citation 拦截"碰巧"给出的安全结局，Agent 从未真正查证 |
| E (4 turns) | instructor | refused/refused/completed/completed | 0+0+0+0 | 1+1+2+1 | 24.0s | FAIL | 整个 4 轮对话 0 次仓库工具：T1/T2 拒答，T3 用通用 MCP 知识答非所问（wrong-subject completion），T4 诚实承认"没找到代码"但 docs↔code 对照未做 |

**Strict 分布：PASS 1 / PARTIAL 1 / FAIL 8 / INFRA 0。Terminal：completed 4 / refused 6。**

## 2. Failure distribution（主要失败归因）

- `evidence_acquisition`（主 blocker，重复出现）：A2、A3、D、E-T1～T4 共 7/10 问
  题零仓库证据获取——模型对 repo-specific 问题不主动调用 code_search /
  read_project_context；B、C 则是"找对了起点但读错了下一跳"（B 不读 doc、C 不读
  test 文件）。
- `terminal_outcome`：B、C、D、E-T1 四题以 INSUFFICIENT_EVIDENCE_TO_FINALIZE 终止，
  用户得不到任何答案文本。
- `refusal`：A3、E-T2 两次 0 工具即 INSUFFICIENT_INFORMATION（over-refusal）。
- `semantic_grounding`：E-T3 用通用语料内容冒充对 instructor 的回答（流畅、有引用、
  但对象错误）。
- `planning/routing`（辅助）：A2/D/A3/E 全部路由 NO_ADDITIONAL_REQUIREMENT——冻结
  router 的 project-scope 词表不含"源码"单独出现、"对照"不在 consistency 词表，
  导致 grounding guard 对 repo-specific 问题不生效（E-T4 docs↔code 问题因此放行
  knowledge-only completion）。
- `context_resolution`：多轮上下文传递本身工作（E-T3/T4 能看到前文），但未促使仓库
  取证（PARTIAL）。
- 未出现：infrastructure 0 例；unsupported_material_claim 以"答非所问"形式出现在
  E-T3（归入 semantic_grounding）。

## 3. 三个必答问题

**Q1 当前最主要 Product blocker 是什么？**
`evidence_acquisition`：对"陌生仓库的工程问题"，Agent 在 7/10 个问题上没有读取目标
仓库的任何代码/文档就作答、拒答或被拦截。其余失败大多是其下游：不读仓库 → requirement
不满足或引用无物可引 → finalization 拦截或错误完成。

**Q2 旧 15D 的 evidence_acquisition / semantic_grounding 问题是否在 fresh repo 上重现？**
- evidence_acquisition：**重现且更严重**。15D 是"读了但读不全/读错 span"；本次是
  "多数问题根本不启动读取"（0 工具调用 ×6）。
- semantic_grounding：以两种新形态重现——(a) 新 [E#] citation contract 对真实模型
  的遵循度不稳定（B/D/E-T1 的 proposed answer 被 binding 拦截，具体 MISSING/INVALID
  不可观测）；(b) 答案语义指向错误对象（E-T3 用通用 MCP 知识回答 instructor 的
  retry 链）。

**Q3 偶发 case 还是重复、通用、值得 Product intervention？**
重复且通用：0-工具行为在两个独立仓库、单轮与多轮、不同问题类型上重复 7 次；
citation 拦截重复 3 次（1 次发生在正确取证之后）；over-refusal 重复 2 次。
不是单 case 噪声，值得 Product intervention。

## 4. Citation 实际表现（Grounding v1 首次真实暴露）

- completed 的 4 个回答（A1/A2/E-T3/E-T4）citation binding 全部 VALID——一旦模型
  遵守 [E#] 契约，机制链路（catalog → 引用 → 校验 → 放行）工作正常，A1 甚至精确
  引用到正确文件+行号 span。
- 但 4 个 run 的 proposed answer 被绑定检查拦截（B/D/E-T1，加 C 的 requirement 侧
  拦截）：真实模型并不稳定输出合法 [E#] 引用；被拦截的答案文本与其具体 binding
  状态（MISSING/INCOMPLETE/INVALID）在公开契约中不可观测（用户只见
  INSUFFICIENT_EVIDENCE_TO_FINALIZE）。
- 结论：机制正确、模型遵循度是新的真实短板；且拦截答案不可观测，妨碍归因。

## 5. Multi-turn 实际表现

服务器侧会话/持久化/有界上下文（6 messages / 1200 tokens）全部正常：4 轮走同一个
server conversation，T3 在一次 parse repair 后完成。但调查质量失败：4 轮全部 0 仓库
工具，T2 对自己 T1 的主题直接拒答，T3 答非所问。多轮框架 ≠ 多轮调查能力。

## 6. Evidence Acquisition / Refusal 实际表现

- Acquisition：10 问中仅 3 问（A1、B、C）取得仓库证据；A1 证明链路本身可以工作；
  B/C 找对起点后下一跳决策错误（B 用最后一次工具重复搜索而非读 doc；C 调了
  find_tests 却不读任何 test 文件）。
- Refusal：2 次 0 工具的 over-refusal（A3、E-T2）；1 次结果正确但机制偶然的
  justified refusal（D）。没有 under-refusal 式幻觉模块路径（D 未编造）。

## 7. Cost / latency（Observed fact）

- 总墙钟：10 问合计 ≈ 54.2s（单问 2.0s–15.1s）。
- Decision LLM calls（trace 可观测部分）：21 次（含 1 次 parse repair）。
  Planner 调用（每 run 1 次）与多轮 context-resolver 调用未在公开契约中计数，
  合计约 +10/+3，记为未插桩。
- input/output tokens：公开契约不暴露 → 全部 UNKNOWN。
- Provider/infra 失败：0。

## 8. Decision

**B — GENERAL PRODUCT BLOCKER REPRODUCED。**
唯一最高优先 failure category：**evidence_acquisition**
（repo-specific 问题不启动/不坚持仓库取证；含 B/C 的"下一跳"目标错误）。

→ **NEXT = PRODUCT-REPAIR-23**（处理该 blocker；citation 遵循度与 router 词表
缺口作为归因记录带入，不得在本任务内顺手修改）。

按 Contamination Rule：本 Set A 自被用于指导 REPAIR-23 起即为 Dev/Diagnostic
Set；PRODUCT-ACCEPT-25 必须使用新的 Fresh Set B。

## 9. Observed fact / Manual judgment / Inference 划分

- **Observed fact**：所有 terminal/status/tool_calls/latency/evidence 卡片内容/
  citation 出现与否/trace 计数（runs/*.json 原样保存，含 SSE 事件流）。
- **Manual judgment**：Strict PASS/PARTIAL/FAIL、Evidence Support、Correct Code
  Path/Span、Refusal 分类——每一条 YES/NO 均对照 pinned 仓库源码人工核验
  （config.py:120、agent.py:1235/1243、base.py:93、client.py:941、retry.py
  `_max_attempts`、13 文件 diff、未跟踪新测试文件等）。
- **Inference**：被拦截 proposed answer 的具体 binding 状态（不可观测，只能推断
  为 citation/requirement 侧未通过）；planner/context 调用次数（未插桩，估值）；
  "若 HyDE 存在 D 也会同样 0 工具作答"的反事实。

## 10. Known limitations of this validation

- 10 个问题、2 个仓库的样本量；结论是 blocker 复现证据，不是通过率统计。
- 被拦截答案与 binding 细节不可观测（Product 公开契约无此暴露），归因存在盲区。
- reviewer 与 scenario 设计者为同一方；Set A 的题目由冻结契约事先固定以缓解。
- runner 的 import-bootstrap 修复发生在任何请求发出之前（首启即崩，未产生任何
  run 数据），不影响冻结纪律；除此之外全程零修改。
