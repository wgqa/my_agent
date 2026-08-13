# 69-Gate3-Planner-Dev真实调用与校准评测

> G3-DECOMP-04B-02A：在公开 Gate 3 Dev 24 Case 上运行已审计 Planner 的第一次真实模型 baseline、可复现校准 Runner 与人工语义审查。
> 日期：2026-08-13
> run_id：`497808269bdd`；provider/model：deepseek / deepseek-chat；Prompt：gate3_planner_prompt_v1（`5b209054...`）；source_commit：`ede4ec6d`。
> 权威来源：实现 `evaluation/gate3/planner_dev.py`、`scripts/run_gate3_planner_dev.py`；测试 `tests/test_gate3_planner_dev.py`；外部 Artifact `benchmark_work/gate3/dev_runs/497808269bdd/`。
> 范围声明：本任务只建立调优前 baseline，禁止修改 Prompt 或根据结果修代码；不运行 Dev/Holdout 检索指标；示例除 baseline 聚合结果外均为 synthetic。

---

## 1. Fake Client 测试与真实 Provider 验证的区别

- **Fake Client 测试**（04B-01）：注入假 client，返回预设响应/抛预设异常，验证"调用逻辑正确"。它证明的是**代码行为**：请求参数对不对、异常怎么映射、单次调用、不泄漏 Key。
- **真实 Provider 验证**（本任务）：用真实 DeepSeek 跑 24 个 Dev Case，看 Prompt v1 在**真实模型**上的行为。它证明的是**Prompt 效果**：模型到底怎么分类、怎么拆解、守不守输出契约。

两者缺一不可：Fake 保证"逻辑没写错"，真实保证"Prompt 在这个模型上真的可用"。Fake 永远无法代替真实——模型对 Prompt 的真实反应只有真调一次才知道。

## 2. 为什么先跑零调优 baseline

"先 baseline 再调优"是受控实验的铁律：

- 没 baseline，你就不知道"现在的 Prompt 起点在哪"，后续任何改动都无法量化收益；
- 调优是"改 Prompt 看效果"，但**在 baseline 之前调优**，你其实是在用自己的直觉盲调，没有参照系；
- baseline 是**冻结的原始快照**——即使结果很差（本任务 schema validity 只有 0.875），也必须如实保留，因为它是"改动前"的证据。

本任务明确**禁止**在看到结果后修改 Prompt。修复属于 04B-02B，且必须与这个 baseline 对照。

## 3. Dev 与 Holdout 的不同职责

- **Dev（24 Case）**：开发与调参的数据。你可以看逐条结果、分析失败、改 Prompt、调阈值。**Dev 上的分数可以被调高**，因为它参与了你的决策。
- **Holdout（12 Case，sealed）**：只运行一次、只用于最终泛化证明。它在整个开发期被物理/流程隔离，任何基于它的调参都使其失效。

本任务只接触 Dev。实现 Agent 全程不读 Holdout——这是"泛化证明还可信"的前提。

## 4. 为什么不能看着 Holdout 调 Prompt

看着 Holdout 结果改 Prompt = 用测试集拟合。之后跑出的分数不再是"没见过的新题的表现"，而是"背过答案的表现"。

本项目把 Holdout 物理封存在 `gate3/sealed/`，实现 Agent 只拿 Dev。一旦同一实现会话读入 Holdout 内容，该 Holdout 立即失效。所以 Dev baseline、失败分析、Prompt 调优全部在 Dev 上进行，Holdout 只留给独立评测会话跑一次。

## 5. Planner 的输入、输出和信任边界

- **输入**：只有 `original_query`。case_id、query_type、Gold、decomposition_expected、relevant_files、obligation **绝不进** Planner——否则就是泄漏。
- **输出**：`PlannerOutcome` = 规范化 QueryPlan（query_type/retrieval_required/action/reason_code/subqueries）+ fallback_used + failure_code + call_metadata。
- **信任边界**：模型输出是**不可信输入**，经 `parse_planner_output` 严格解析（五字段白名单、重复 key 拒绝、枚举校验、跨字段不变量）后才成为可信 QueryPlan；任何失败回退系统 `unknown`。

Runner 的 `plan(case.query)` 只传 query，Gold 在调用完成后才用于指标计算——代码与测试都验证了这一点。

## 6. schema validity、fallback、分类准确率的区别

- **schema_validity**：模型输出是否通过了结构校验（能成为合法 QueryPlan）。`schema_valid_count / case_count`。本任务 21/24 = 0.875。
- **fallback_rate**：未能产出计划、回退系统 `unknown` 的比例。本任务 3/24 = 0.125。
- **分类准确率（query_type exact）**：预测 query_type 是否与 Gold 完全一致。本任务 16/24 = 0.667（全 case），非 fallback 子集 0.762。

三个数字回答不同问题：格式守不守、规划成不成功、分类对不对。不能混为一谈。

## 7. unnecessary 与 missed decomposition

- **unnecessary decomposition**：Gold 不该分解（forbidden），模型却拆了。本任务 2 条（g3q031/g3q033，unanswerable 题被当可答拆解）。
- **missed decomposition**：Gold 该分解（required），模型却没拆。本任务 1 条（g3q021 fallback 后变 single）。

分母都是 `case_count`。这两个指标反映 Prompt 对"什么时候该拆"的引导是否到位。

## 8. 为什么 fallback 在分类准确率中不能冒充 Gold 类型

fallback 的 query_type 是系统专属 `unknown`——它不代表任何业务类型。如果拿 Gold 的 query_type 去填 fallback 再算准确率，等于"假装模型猜对了"，掩盖了它根本没输出可用计划的事实。

本任务 fallback 一律按**分类错误**计（`query_type_correct=False`），且单独统计 fallback_rate。所以全 case 准确率 0.667 低于非 fallback 子集 0.762——差异正是 3 条 fallback 造成的。

## 9. Prompt version/hash 与 run identity

- `PLANNER_PROMPT_VERSION = gate3_planner_prompt_v1`、`PLANNER_PROMPT_SHA256`（canonical 绑定 system prompt 全文 + user payload 模板结构 + canonicalization）。
- `planner_dev_run_id` = canonical JSON（绑定 schema_version / source_commit / corpus_id / evaluation_set_id / dev_jsonl_sha256 / provider / model / prompt_version / prompt_sha256 / temperature / max_tokens / timeout / max_retries）SHA-256[:12]。**不绑定** API Key、base_url、路径、时间、latency。
- 这样：换 provider/model/Prompt/commit 任一，run_id 必变；同配置重跑 run_id 恒定。测试硬编码验证了"时间/latency/路径变化 run_id 不变"。

## 10. API Key 和异常信息安全

- API Key 只从环境变量 `DEEPSEEK_API_KEY` 读取，CLI 只接受**环境变量名**，不接受 Key 值；缺失时在任何网络调用/Artifact 写入前失败。
- 本任务全程不打印、不提交 Key。
- run_config / planner_results / planner_metrics / result.json 均**不含** API Key、base_url、本地绝对路径、raw model response、异常字符串、traceback——测试断言了这一点。

## 11. 单次调用、无 retry 与成本可复现性

每 Case 恰好调用一次 Planner（`planner_call_count = 24` = case_count）。无 retry、无 sleep、无第二次调用。原因：

- 重试把一次失败变两次随机机会，成本/延迟不可控，实验身份无法冻结；
- 成本（token）随调用次数线性增长，超出有界预算；
- 只有"每 Case 一次调用"才能保证 run 可复现、可对照。

本任务 token 总量：input 13943、output 3195，全 24 条均有 usage（missing_usage=0）。

## 12. 人工语义审查为何不能被简单字符串规则代替

自动规则能确定性判断"query 字符串完全重复"（exact duplicate），但**不能**判断语义问题：

- **新实体**：缩写、全称、同义词需要人判断。子问题引入"奖励模型"在"偏好优化"题里是不是新实体？字符串不匹配不能自动认定。
- **比较两侧保留**：需要理解语义才知道"两侧对象都在"。
- **语义近义重复**："RLHF 的偏好数据"和"DPO 的偏好数据"字符串不同但语义不同——规则会误报或漏报。

所以本任务用**人工逐条审查**（PASS/FAIL/UNCERTAIN），并明确"不把人工判断伪装成自动指标"、不用同一个模型当 Judge。

## 13. 本次 baseline 的聚合结果

| 指标 | 值 |
|---|---|
| case_count / completed / planner_call_count | 24 / 24 / 24 |
| schema_valid_count / rate | 21 / 0.875 |
| fallback_count / rate | 3 / 0.125（全为 PLAN_INVALID_SCHEMA） |
| query_type exact accuracy（all / non-fallback） | 16/24=0.667 / 16/21=0.762 |
| retrieval_required accuracy | 23/24=0.958 |
| action accuracy | 20/24=0.833 |
| unnecessary / missed decomposition | 2（0.083）/ 1（0.042） |
| exact duplicate subquery | 0 |
| input/output tokens、missing usage | 13943 / 3195 / 0 |
| latency P50/P95 | 1742ms / 2298ms |
| timeout / provider_error | 0 / 0 |

按 query_type 的 query_type exact accuracy：comparison/causal/code_symbol=1.0、troubleshooting=0.667、fact=0.5、multi_entity=0.25、unanswerable=0.25。

## 14. 当前失败类型及后续 04B-02B 决策依据

1. **3 条 fallback（g3q021/g3q025/g3q034）**：模型输出 Schema 无效。04B-02B 需在开发环境对 fallback 保留受限 raw-output 诊断日志（不进结果对象），定位格式/内容问题。
2. **multi_entity 误判（g3q006/008/018 → causal/troubleshooting）**：Prompt 需澄清 multi_entity 边界。
3. **unanswerable 误判为可答（g3q031/033，触发 2 条 unnecessary decomposition）**：模型无法仅凭问题判断 KB 覆盖度；Prompt 只能缓解，可能需规划后确定性"领域边界核验"候选 Guard（谨慎评估）。
4. 这些是 **04B-02B 的决策输入**，不是本任务要修的问题。baseline 如实保留。

## 15. 面试常见追问与回答

**Q：Fake Client 测试和真实调用为什么都要？**
A：Fake 验证"逻辑没写错"（参数、异常映射、单次调用、防泄漏），真实调用验证"Prompt 在真实模型上可用"（分类、拆解、守契约）。Fake 无法代替真实，因为模型对 Prompt 的真实反应只有真调一次才知道。

**Q：为什么先跑零调优 baseline？**
A：没 baseline 就没有参照系，后续改 Prompt 无法量化收益。baseline 是冻结的原始快照，即使差也要保留，因为它是"改动前"的证据。本任务明确禁止看到结果后改 Prompt。

**Q：Dev 分数能证明泛化吗？**
A：不能。Dev 参与调参，分数可被调高；泛化只能由从未接触的 sealed Holdout 证明。看着 Holdout 调 Prompt 会使 Holdout 失效。

**Q：fallback 为什么在分类准确率里按错算？**
A：fallback 的 query_type 是系统 unknown，不代表任何业务类型。拿 Gold 填 fallback 等于假装模型猜对了。fallback 单独统计，且按分类错误计入全 case 准确率。

**Q：run_id 绑定了什么？**
A：canonical JSON（schema_version/source_commit/corpus_id/evaluation_set_id/dev_jsonl_sha256/provider/model/prompt_version/prompt_sha256/temperature/max_tokens/timeout/max_retries）SHA-256[:12]。不绑定 API Key、base_url、路径、时间、latency。换任一身份字段 run_id 变，同配置恒同。

**Q：为什么每 Case 只调一次 Planner？**
A：重试会把一次失败变两次随机机会，成本/延迟/身份无法冻结。有界预算要求单次调用，run 才能可复现、可对照。

**Q：人工语义审查能自动化吗？**
A：exact duplicate 可以（字符串）。新实体、比较两侧、语义近义必须人工——缩写/同义词/字符串不匹配不能自动认定。不把人工判断伪装成自动指标。

**Q：本任务为什么不算检索指标？**
A：本任务只做 Planning 层。obligation coverage、Hit@5、Recall、MRR、nDCG 属于检索/证据评测（G3-MRETR-05 及之后），且要求真实检索执行。本 baseline 只回答"Planner 规划行为如何"。

---

## 边界声明

- 本 baseline 只覆盖公开 Dev 24 Case，不推广为 Holdout 或跨语料泛化结论。
- 人工语义审查是人工判断，非自动指标；未隐藏失败 Case。
- 未运行 Retriever/Reranker/Generator/Router；未计算任何检索/答案指标。
- 未调用真实模型之外的任何外部服务；未访问 sealed/Holdout。
