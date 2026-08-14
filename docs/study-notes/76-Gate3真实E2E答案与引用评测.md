# 76-Gate3真实E2E答案与引用评测

> G3-E2E-07A：Gate 3 第一次真实完整链路答案评测。Dev 24 Case 上跑
> Real Planner → Adaptive Router v1 → Retrieval → subquery_rrf_merge_v2(k=60)
> → Evidence Verifier → Real Generator → Citation Validator → Answer。
> 日期：2026-08-14
> run_id：`4172f6cc1d6f`；source_commit：`6a783c4862b18d7dc9f35069dd6cde0fad507925`（Commit 1，tracked-clean 绑定）。
> 配置：planner=deepseek-chat（gate3_planner_prompt_v1，temp 0，max_tokens 800，retries 0）；
> generator=deepseek-v4-flash（temp 0.3，max_tokens 800，retries 2）；
> judge=deepseek-chat（gate3_answer_judge_prompt_v1，temp 0，max_tokens 800）。
> 生产链路 = 06C 选定候选 D：adaptive_retrieval_policy_v1 + subquery_rrf_merge_v2(k=60) + max_evidence_items=5。
> 外部 Artifact：`benchmark_work/gate3/e2e_dev_runs/4172f6cc1d6f/`（不入 Git）。

---

## 0. 结论先行（真实数字）

**Dev 24 上真实 E2E：20/24 completed、4/24 GENERATION_FAILED；answer_pass=8/20、answer_obligation=21/44=0.477。**

| 层 | 指标 | 值 |
|---|---|---|
| 运行 | status 分布 | completed 20 / failed 4 |
| 运行 | planner fallback | 3（均 PLAN_INVALID_SCHEMA → single_retrieval） |
| 运行 | retrieval calls | 50 |
| 检索（确定性） | obligation 覆盖 | 35/44=0.795（06C D 参考 37/44） |
| 检索（确定性） | document Hit@5 / Recall@5 | 0.95 / 0.833 |
| citation（确定性） | invalid citation / uncited evidence | 0 / 56 |
| citation（answerable） | citation valid | 16/16=1.0（有答案的 answerable） |
| 答案 | answer_obligation 覆盖 | 21/44=0.477 |
| 答案 | answer full coverage | 8/20 |
| 答案 | unsupported material claim | 0 |
| 答案 | no-answer（GENERATION_FAILED） | 4 |
| 答案 | **answer_pass** | **8/20=0.40** |

非 answerable 4（g3q031/g3q033/g3q034/g3q036）单独上报：unanswerable 两题正确回答"资料不足"，no_retrieval 两题正确做确定性计算（如"[1,2,4,7]"、KV Cache 求和）。

关键观察：**检索覆盖 35/44 但答案覆盖只有 21/44**——证据召回 ≠ 答案覆盖。generator 即使拿到证据，也未必覆盖每个 Gold obligation。另有 4 个 case 因 generator（deepseek-v4-flash）对大上下文输出空串而失败。

## 1. Retrieval evaluation 和 answer evaluation 为什么不是一回事

- **检索评测**只问"该引的文件引到没有"：final evidence 的 canonical paths 是否命中 Gold `relevant_files`（document/obligation 覆盖）。它在 merge 之后、生成之前就能算。
- **答案评测**问"答案是否真的覆盖了每个必须回答的方面、引用是否有效、有没有幻觉"。它必须读生成答案 + Judge 判定。

证据覆盖高不代表答案覆盖高：generator 可能引了证据却没回答该义务要求的方面，或者只答了一半。07A 里 retrieval obligation 0.795 → answer obligation 0.477，差 0.32，就是"召回→生成"这一段的损失。

## 2. Gold leakage 为什么会让实验失效

如果 Generation stage 能看到 Gold obligation / relevant_file / expected answer，generator 就能"对着答案抄"，测出来的不是系统的检索+生成能力，而是**提示词里泄题**。那 24 个 case 的分数全部失真，07A 作废。

07A 的硬隔离：GenerationCase 只含 `case_id + query`（dataclass 字段被测试锁定为恰好这两个）；生成记录 `case_results.jsonl` 不含任何 Gold 字段（有测试断言）；Evaluation stage 才离线读 Dev Gold 喂给 Judge。**先持久化原始生成结果，再进 Evaluation**——边界清晰、可审计。

## 3. Citation validity、correctness、groundedness 的区别

- **Validity（有效性，本实验的确定性层）**：答案里 `[Cx]` 的编号是否都真实存在于本次 evidence（没有编造不存在的引用号）。07A：有答案的 16 个 answerable case 全部 valid（invalid citation=0），但 uncited evidence 56 条（大量 evidence 没被引用）。
- **Correctness（正确性）**：引用的内容是否真的是该来源里的事实（这里没做 claim-level 校验）。
- **Groundedness（可溯源）**：答案里的每个实质主张是否都被证据支撑——这是 Judge 的 unsupported material claim 检测。07A：unsupported=0。

三层逐步递进；本实验确定性层只测 validity，correctness/groundedness 交给 Judge 辅助。

## 4. LLM-as-a-Judge 的原理与偏差

Judge 用 `gate3_answer_judge_prompt_v1`，对每个 Gold obligation 输出结构化 covered/not_covered，并列出 unsupported material claims。它只在生成完成后读取 query/answer/cited evidence/Gold，**不改变答案**。

偏差必须明说：① LLM Judge 不是人工 Ground Truth，可能漏判/误判；② **same-model bias**：若 Judge 与 Generator 用同一模型，Judge 容易给"同源风格"的答案放水。本实验 Judge=deepseek-chat、Generator=deepseek-v4-flash，不同模型降低了同模型偏置，但同属 DeepSeek 家族，仍不构成独立第三方；③ Judge 输出是结构化的，有严格 parser + invalid fallback（无法解析的判为 invalid，单独计数），不把主观分当核心。

## 5. 为什么 06C 用 snapshot Planner，而 07A 必须用 live Planner

- **06C 是检索对照**：要隔离"执行方式"变量，所以 24 个 case 的 plan 必须冻结（用 497808269bdd 快照），否则 A/B/C/D 差异混入"Planner 变了"。snapshot 保证四组唯一差异是 merge。
- **07A 是端到端评测**：要测真实系统的整体能力，Planner 本来就是系统一部分。用 live Planner 才能暴露真实规划质量——07A 就是来测"开箱即用的 Gate 3 到底行不行"。frozen snapshot 只作为运行后的漂移参考。

## 6. 真实 Planner 漂移（live vs frozen snapshot 497808269bdd）

- **plan_id 精确一致：5/24**。
- **语义一致（query_type/action/subquery_count/fallback 全同）但 plan_id 不同：16/24**——live planner 的 subquery 措辞与冻结快照不同，plan_id 是含 subqueries 的哈希，措辞一变就变。
- fallback_delta 2（g3q025/g3q027）+ subquery_count delta 1（g3q007）。
- fallback 总数 3 vs 3（同为 3，但具体 case 有出入；live 3 个均 PLAN_INVALID_SCHEMA）。

**漂移的后果**：live 计划产生略差的检索（obligation 35/44 vs 06C D 的 37/44）。这是诊断信息，不是调参目标——07A 不做"偷偷重跑挑最好"。

## 7. 失败与限制（如实报告）

- **4 个 case GENERATION_FAILED（g3q008/g3q012/g3q015/g3q016）**：均为 decomposed（causal/comparison），generator=deepseek-v4-flash 对这些大上下文 prompt 返回**空串**。诊断确认 deepseek-chat 对同一 prompt 能产出带 [Cx] 的答案，deepseek-v4-flash 返回空。按任务停止规则"不要自己换模型再跑"，原样保留：这是当前生产 generator 配置的真实行为。answer_pass 分母仍是 20（4 个 no-answer 计入分母但不计 pass）。
- **answer_obligation 0.477 < retrieval 0.795**：generator 拿到证据也常只答一部分义务。
- **uncited evidence 56 条**：evidence=5 时答案只引用一部分，剩余证据浪费（不判为错误，只是信息利用率低）。

## 8. 面试如何讲 Gate 3 实验链

一条线讲清：
1. **数据**：Dev/Holdout 24/12 分层封存，Gold 是 obligation 级（每个"必须回答的方面"对应相关文件），保证可评测。
2. **规划**：强类型 QueryPlan + 确定性 Router + Adaptive Policy（BM25/Hybrid 策略表），不调用 LLM 路由。
3. **检索**：冻结语料 Hybrid，RRF merge v2（rank-based 融合）把 merge-drop 从 5 降到 0，final obligation 32→37。
4. **对照**：06B 先证明"分解检索不如原问题 BM25"（负结果），06C 证明"换 merge 选择能止损反超"（正结果）——单变量控制。
5. **端到端**：07A 接真实 Planner + 真实 Generator，两阶段 Gold 隔离，确定性 citation + LLM Judge 分层评测，answer_pass=8/20。

要点：**先证明检索，再证明生成；每次只动一个变量；Gold 隔离是实验生命线；负结果和正结果同样有价值**（06B 负 → 06C 修 merge；07A 暴露 generator 空输出）。

---

## 边界声明

- 未读取/搜索 Gate 3 sealed/Holdout；只用了公开 Dev、冻结 corpus、冻结 planner snapshot（仅漂移参考）。
- 未运行 Holdout；未跑 A/B/C 竞赛；未做模型/temperature/prompt grid；未扩 Evidence。
- Generation stage 严格 Gold 隔离（有测试证明）；Judge 为辅助评测，非人工 Ground Truth；Generator 与 Judge 用不同模型但同属 DeepSeek 家族。
- API Key 只来自环境变量，Artifact 无 Key/raw response/COT/header（有 redaction 校验）。
- Dev-only 单次受控观测；泛化结论需独立评测会话跑 sealed。
